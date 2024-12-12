import os
import re
import sqlite3
import csv
import hashlib
import logging
import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from flask import Flask, render_template, request, jsonify
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Spell Categories
CATEGORIES = {
    "Healing": ["Cure Wounds", "Healing Word", "Mass Healing Word", "Regenerate", "Heal", "Lesser Restoration", "Greater Restoration"],
    "Offensive": ["Fireball", "Magic Missile", "Eldritch Blast", "Shatter", "Inflict Wounds", "Disintegrate", "Meteor Swarm"],
    "Control": ["Wall of Force", "Hold Person", "Entangle", "Web", "Earthbind", "Evard’s Black Tentacles", "Dominate Person"],
    "Debuffing": ["Ray of Enfeeblement", "Bestow Curse", "Bane", "Slow", "Blight", "Hex", "Contagion"],
    "Buffing": ["Bless", "Shield of Faith", "Haste", "Enhance Ability", "Heroism", "Aid", "Freedom of Movement"],
    "Utility": ["Detect Magic", "Identify", "Knock", "Teleportation Circle", "Pass Without Trace", "Unseen Servant", "Prestidigitation"],
    "Defensive": ["Shield", "Counterspell", "Absorb Elements", "Sanctuary", "Globe of Invulnerability", "Mage Armor", "Stoneskin"],
    "Summoning": ["Conjure Animals", "Conjure Elemental", "Summon Fey", "Find Familiar", "Summon Greater Demon", "Create Undead", "Planar Ally"]
}

# Step 1: Fetch PDF URLs from GitHub Repository
def fetch_pdf_urls(github_url):
    """Scrape the GitHub repository page for PDF file links."""
    response = requests.get(github_url)
    if response.status_code != 200:
        logging.error(f"Failed to fetch GitHub URL: {response.status_code}")
        raise Exception(f"Failed to fetch GitHub URL: {response.status_code}")

    soup = BeautifulSoup(response.text, 'html.parser')
    pdf_urls = []
    base_url = "https://raw.githubusercontent.com"

    for link in soup.find_all('a', href=True):
        href = link['href']
        if href.endswith('.pdf'):
            # Convert the GitHub link to raw content URL
            raw_url = href.replace('/blob/', '/')
            if not raw_url.startswith('http'):
                raw_url = base_url + raw_url
            pdf_urls.append(raw_url)

    logging.info(f"Found {len(pdf_urls)} PDF files.")
    return pdf_urls

# Step 2: Download PDF Files with Hash Check
def get_file_hash(file_path):
    """Calculate the SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()

def download_pdfs(pdf_urls, download_directory):
    """Download PDFs from a list of URLs to a local directory."""
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    for url in pdf_urls:
        file_name = os.path.join(download_directory, os.path.basename(url))
        response = requests.get(url)
        if response.status_code == 200:
            if os.path.exists(file_name):
                new_hash = hashlib.sha256(response.content).hexdigest()
                existing_hash = get_file_hash(file_name)
                if new_hash == existing_hash:
                    logging.info(f"File {file_name} is unchanged. Skipping download.")
                    continue
            with open(file_name, 'wb') as file:
                file.write(response.content)
            logging.info(f"Downloaded {file_name}")
        else:
            logging.error(f"Failed to download {url}: {response.status_code}")

# Step 3: Parse PDF Files and Categorize Spells
def categorize_spell(spell_name):
    """Determine the category of a spell based on its name."""
    for category, spells in CATEGORIES.items():
        if spell_name in spells:
            return category
    return "Unknown"

def parse_pdf(pdf_path):
    """
    Extract text from a PDF and return a list of potential spell details with categories.
    """
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    
    # Example: Use regex to find spell information
    spell_pattern = re.compile(r"(?P<name>[A-Za-z ]+)\nLevel: (?P<level>[0-9]+)\nClass: (?P<class>[A-Za-z, ]+)")
    spells = []
    for match in spell_pattern.finditer(text):
        name = match.group("name")
        category = categorize_spell(name)
        spells.append({
            "name": name,
            "level": int(match.group("level")),
            "class": [cls.strip() for cls in match.group("class").split(",")],
            "category": category
        })
    logging.info(f"Parsed {len(spells)} spells from {pdf_path}")
    return spells

# Step 4: Create Database and Insert Spells
def create_database(db_path):
    """Create SQLite database to store spells."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            level INTEGER,
            class TEXT,
            category TEXT
        )
    """)
    conn.commit()
    conn.close()
    logging.info(f"Database created at {db_path}")

def insert_spells(db_path, spells):
    """Insert spells into the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for spell in spells:
        cursor.execute(
            "INSERT INTO spells (name, level, class, category) VALUES (?, ?, ?, ?)",
            (spell["name"], spell["level"], ",".join(spell["class"]), spell["category"])
        )
    conn.commit()
    conn.close()
    logging.info(f"Inserted {len(spells)} spells into the database.")

def save_spells_to_csv(spells, csv_path):
    """Save spells to a CSV file."""
    with open(csv_path, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Name", "Level", "Class", "Category"])
        for spell in spells:
            writer.writerow([spell["name"], spell["level"], ",".join(spell["class"]), spell["category"]])
    logging.info(f"Saved spells to CSV file at {csv_path}")

def save_spells_to_excel(spells, excel_path):
    """Save spells to an Excel file."""
    df = pd.DataFrame(spells)
    df["class"] = df["class"].apply(lambda classes: ",".join(classes))
    df.to_excel(excel_path, index=False, sheet_name="Spells")
    logging.info(f"Saved spells to Excel file at {excel_path}")

# Step 5: Query Spells Based on User Input
def query_spells(db_path, user_class, user_level, category=None):
    """Retrieve spells based on class, level, and optional category."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if category:
        cursor.execute(
            "SELECT name FROM spells WHERE class LIKE ? AND level <= ? AND category = ?",
            (f"%{user_class}%", user_level, category)
        )
    else:
        cursor.execute(
            "SELECT name FROM spells WHERE class LIKE ? AND level <= ?",
            (f"%{user_class}%", user_level)
        )
    results = cursor.fetchall()
    conn.close()
    return [row[0] for row in results]

# Step 6: Flask Web Application
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def query():
    user_class = request.form.get('class')
    user_level = int(request.form.get('level'))
    category = request.form.get('category')
    db_path = "spells.db"
    spells = query_spells(db_path, user_class, user_level, category)
    return jsonify(spells)

if __name__ == "__main__":
    github_url = "https://github.com/gman4161/DnD-3.5e-Books"
    pdf_directory = "pdf_files"  # Directory to store downloaded PDFs
    db_path = "spells.db"
    csv_path = "spells.csv"
    excel_path = "spells.xlsx"

    # Fetch PDF URLs and Download
    pdf_urls = fetch_pdf_urls(github_url)
    download_pdfs(pdf_urls, pdf_directory)

    # Parse PDFs and Build Database
    create_database(db_path)
    all_spells = []
    for pdf_file in os.listdir(pdf_directory):
        if pdf_file.endswith(".pdf"):
            pdf_path = os.path.join(pdf_directory, pdf_file)
            spells = parse_pdf(pdf_path)
            insert_spells(db_path, spells)
            all_spells.extend(spells)

    # Save spells to CSV and Excel
    save_spells_to_csv(all_spells, csv_path)
    save_spells_to_excel(all_spells, excel_path)

    # Run Flask App
    app.run(debug=True)
