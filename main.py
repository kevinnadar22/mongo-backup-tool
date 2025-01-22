import streamlit as st
import pymongo
from pymongo.errors import ConnectionFailure
import json
import os
from datetime import datetime
import shutil
import threading
import time
import subprocess
import platform

# Constants
MAX_EXPORT_SIZE = 512 * 1024 * 1024  # 512MB in bytes
BACKUP_RETENTION_HOURS = 1
OUTPUT_DIR = "backups"
SOURCE_URL = "https://github.com/kevinnadar22/mongo-backup-tool"


# Check if mongodump is installed
def is_mongodump_installed():
    try:
        subprocess.run(["mongodump", "--version"], capture_output=True)
        return True
    except FileNotFoundError:
        return False


def get_mongodump_install_instructions():
    system = platform.system().lower()
    if system == "windows":
        return "Install MongoDB Database Tools from: https://www.mongodb.com/try/download/database-tools"
    elif system == "darwin":  # macOS
        return (
            "Install using Homebrew: `brew install mongodb/brew/mongodb-database-tools`"
        )
    else:  # Linux
        return "Install using apt: `sudo apt-get install mongodb-database-tools`"


# remove old backups
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def cleanup_old_backups():
    """Delete backup directories older than BACKUP_RETENTION_HOURS"""
    while True:
        current_time = datetime.now().timestamp()
        for dirname in os.listdir(OUTPUT_DIR):
            if dirname.startswith("backup_"):
                dir_path = os.path.join(OUTPUT_DIR, dirname)
                if os.path.isdir(dir_path):
                    creation_time = os.path.getctime(dir_path)
                    if (current_time - creation_time) > (BACKUP_RETENTION_HOURS * 3600):
                        shutil.rmtree(dir_path)
        time.sleep(300)  # Check every 5 minutes


# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_backups, daemon=True)
cleanup_thread.start()


def get_database_size(db):
    """Calculate total size of a database in bytes"""
    total_size = 0
    try:
        for collection in db.list_collection_names():
            try:
                stats = db.command("collstats", collection)
                total_size += stats.get("size", 0)
            except pymongo.errors.OperationFailure:
                # Skip collections we can't access
                continue
    except pymongo.errors.OperationFailure:
        # If we can't access the database at all, return 0
        return 0
    return total_size


def export_database(db, output_dir):
    """Export a single database to JSON files"""
    db_path = os.path.join(output_dir, db.name)
    os.makedirs(db_path, exist_ok=True)

    for collection in db.list_collection_names():
        docs = list(db[collection].find({}))
        file_path = os.path.join(db_path, f"{collection}.json")
        with open(file_path, "w") as f:
            json.dump(docs, f, default=str, indent=2)


def create_backup(uri, db_names=None, progress_bar=None):
    """
    Create backup using mongodump
    Args:
        uri: MongoDB URI
        db_names: List of database names to backup. If None, backs up all databases
        progress_bar: Optional streamlit progress bar
    Returns:
        (success, output_dir, error_message)
    """
    output_dir = f"{OUTPUT_DIR}/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        if db_names:
            # Backup specific databases
            total_dbs = len(db_names)
            for i, db_name in enumerate(db_names, 1):
                if progress_bar:
                    progress_bar.progress(i / total_dbs, f"Backing up {db_name}...")

                result = subprocess.run(
                    [
                        "mongodump",
                        f"--uri={uri}",
                        f"--db={db_name}",
                        f"--out={output_dir}",
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return (
                        False,
                        output_dir,
                        f"Error backing up {db_name}: {result.stderr}",
                    )
        else:
            # Backup all databases
            if progress_bar:
                progress_bar.progress(0.2, "Backing up all databases...")

            result = subprocess.run(
                ["mongodump", f"--uri={uri}", f"--out={output_dir}"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False, output_dir, f"Error creating backup: {result.stderr}"

            if progress_bar:
                progress_bar.progress(1.0)

        return True, output_dir, None

    except Exception as e:
        return False, output_dir, str(e)


def calculate_total_size(client, db_names=None, progress_bar=None):
    """
    Calculate total size of databases
    Args:
        client: MongoDB client
        db_names: List of database names or None for all databases
        progress_bar: Optional streamlit progress bar
    Returns:
        (total_size, size_details)
    """
    total_size = 0
    size_details = {}
    
    if db_names is None:
        try:
            db_names = client.list_database_names()
        except pymongo.errors.OperationFailure:
            st.error("Insufficient permissions to list all databases")
            return 0, {}
    
    for i, db_name in enumerate(db_names, 1):
        if progress_bar:
            progress_bar.progress(i / len(db_names), f"Analyzing {db_name}...")
        
        db = client[db_name]
        size = get_database_size(db)
        if size > 0:  # Only include databases we can access
            total_size += size
            size_details[db_name] = size
    
    return total_size, size_details


def create_and_offer_download(uri, db_names=None):
    """Create backup and show download button if successful"""
    client = pymongo.MongoClient(uri)
    
    # Calculate total size with progress bar
    with st.spinner("Analyzing databases..."):
        size_progress = st.progress(0)
        total_size, size_details = calculate_total_size(client, db_names, size_progress)
        
        if not size_details:
            st.error("No accessible databases found or insufficient permissions")
            return
            
        if total_size > MAX_EXPORT_SIZE:
            st.error(
                f"""
                💡 Total backup size ({humanbytes(total_size)}) exceeds maximum allowed size ({humanbytes(MAX_EXPORT_SIZE)})
                
                For large databases, please:
                1. [Host this tool yourself]({SOURCE_URL})
                2. Use mongodump directly on your server
                3. Select fewer databases
                """
            )
            return
    
    # Clear the progress bar and spinner
    size_progress.empty()
    
    # Proceed with backup if size is acceptable
    with st.spinner("Creating backup..."):
        progress = st.progress(0)
        success, output_dir, error = create_backup(uri, db_names, progress)
        
        if not success:
            st.error(error)
            progress.empty()
            return

        # Create zip file for download
        progress.progress(0.9, "Creating ZIP file...")
        zip_filename = f"{output_dir}.zip"
        shutil.make_archive(output_dir, "zip", output_dir)
        #  dleete the output_dir after zip file is created
        shutil.rmtree(output_dir)
        
        # Clear the progress bar
        progress.empty()

        st.success("✅ Backup completed! ⚠️ Note: Backup files will be automatically deleted after " + str(BACKUP_RETENTION_HOURS) + " hour(s)")

        with open(zip_filename, "rb") as fp:
            total_size = os.path.getsize(zip_filename)
            st.download_button(
                label=f"📥 Download Backup ZIP ({humanbytes(total_size)})",
                data=fp,
                file_name=os.path.basename(zip_filename),
                mime="application/zip",
            )



def humanbytes(size):
    """Convert bytes to human-readable format"""
    # dynamicaly calculate size in loop, gb, mb, kb, b, tb
    t = ["B", "KB", "MB", "GB", "TB"]
    for i in range(len(t)):
        if size < 1024:
            return f"{size} {t[i]}"
        size /= 1024
        size = round(size, 2)
    return f"{size} {t[-1]}"


st.title("MongoDB Backup Tool")

# Privacy Warning
st.warning(
    f"""
⚠️ **Privacy Notice**: 
- This is a public tool - avoid using it with sensitive data
- For private data, please [host this tool yourself]({SOURCE_URL})
- All backups are automatically deleted after {BACKUP_RETENTION_HOURS} hour
"""
)

if not is_mongodump_installed():
    st.error(
        f"""
    mongodump is not installed! 
    
    {get_mongodump_install_instructions()}
    """
    )
    st.stop()

# URI Input
uri = st.text_input("MongoDB URI", placeholder="mongodb://localhost:27017")

if uri:
    if "localhost" in uri:
        st.info(
            f"""
        ℹ️ Using localhost? You might want to:
        1. [Host MongoDB on Atlas](https://www.mongodb.com/cloud/atlas/register)
        2. [Host this tool yourself]({SOURCE_URL})
        """
        )

    try:
        client = pymongo.MongoClient(uri)
        databases = client.list_database_names()

        # Operation selection
        operation = st.radio(
            "Select Operation", ["Backup Specific Databases", "Backup All Databases"]
        )

        if operation == "Backup Specific Databases":
            selected_dbs = st.multiselect(
                "Select databases to backup", 
                databases,
                help="💡 Select multiple databases to backup. Size will be calculated before proceeding."
            )

            if st.button("Backup Selected Databases"):
                if not selected_dbs:
                    st.error("Please select at least one database")
                else:
                    create_and_offer_download(uri, selected_dbs)

        elif operation == "Backup All Databases":
            st.info("💡 All databases will be backed up. Size will be calculated before proceeding.")
            if st.button("Backup All Databases"):
                create_and_offer_download(uri)

    except ConnectionFailure:
        st.error("Failed to connect to MongoDB. Please check your URI and try again.")
