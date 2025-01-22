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
import zipfile

# Constants
MAX_EXPORT_SIZE = int(os.environ.get("MAX_EXPORT_SIZE", 512 * 1024 * 1024))  # 512MB in bytes
BACKUP_RETENTION_HOURS = int(os.environ.get("BACKUP_RETENTION_HOURS", 1))
OUTPUT_DIR = "backups"
SOURCE_URL = "https://github.com/kevinnadar22/mongo-backup-tool"
GITHUB_URL = "https://github.com/kevinnadar22"

# SEO and Metadata
st.set_page_config(
    page_title="MongoDB Backup & Restore Tool",
    page_icon="💾",
    menu_items={
        "Get Help": "https://t.me/ask_Admin001",
        "Report a bug": "https://github.com/kevinnadar22/mongo-backup-tool/issues",
        "About": f"""
        ### MongoDB Backup & Restore Tool
        A free tool to backup and restore MongoDB databases.
        
        **Author:** Kevin Nadar
        - GitHub: [kevinnadar22](https://github.com/kevinnadar22)
        - Contact: [Telegram](https://t.me/ask_Admin001)
        
        [Source Code]({SOURCE_URL})
        """,
    },
    initial_sidebar_state="collapsed",
)


# Global state for cancellation
if "cancel_backup" not in st.session_state:
    st.session_state.cancel_backup = False


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


# Replace session_state cancel flag with container-based approach
def create_cancel_button(key, container, size_mb=0):
    """Create a cancel button in the given container if size > 10MB"""
    if size_mb > 10:  # Only show cancel for operations > 10MB
        if container.button("❌ Cancel", key=key, use_container_width=True):
            return True
    return False


def calculate_total_size(
    client, db_names=None, progress_bar=None, cancel_container=None
):
    """Calculate total size of databases"""
    total_size = 0
    size_details = {}

    if db_names is None:
        try:
            db_names = client.list_database_names()
        except pymongo.errors.OperationFailure:
            st.error("Insufficient permissions to list all databases")
            return 0, {}

    # First calculate total size
    for db_name in db_names:
        db = client[db_name]
        size = get_database_size(db)
        if size > 0:  # Only include databases we can access
            total_size += size
            size_details[db_name] = size

    # Show progress
    size_mb = total_size / (1024 * 1024)
    if size_mb > 10 and cancel_container:  # Only show cancel for large operations
        cancel_container.button(
            "❌ Cancel", key="cancel_analysis", use_container_width=True
        )

    for i, db_name in enumerate(db_names, 1):
        if progress_bar:
            progress_bar.progress(i / len(db_names), f"Analyzing {db_name}...")
        if st.session_state.get("cancel_analysis", False):
            return 0, {}

    return total_size, size_details


def create_and_offer_download(uri, db_names=None):
    """Create backup and show download button if successful"""
    # Create containers for progress and cancel button in the backup column
    with st.columns((1, 3, 1))[1]:  # Center column for progress
        progress_container = st.empty()
        cancel_container = st.empty()
        status_container = st.empty()

    client = pymongo.MongoClient(uri)

    try:
        # Calculate total size first without showing progress
        total_size = 0
        size_details = {}

        if db_names is None:
            try:
                db_names = client.list_database_names()
            except pymongo.errors.OperationFailure:
                st.error("Insufficient permissions to list all databases")
                return

        # Calculate size first
        with status_container.status("Calculating database size..."):
            for db_name in db_names:
                db = client[db_name]
                size = get_database_size(db)
                if size > 0:
                    total_size += size
                    size_details[db_name] = size

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

        # Show cancel button if size > 10MB
        size_mb = total_size / (1024 * 1024)
        show_cancel = size_mb > 10

        # Start backup process
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if db_names and len(db_names) == 1:
            folder_name = f"{db_names[0]}_{timestamp}"
        elif db_names:
            folder_name = f"multiple_dbs_{len(db_names)}_{timestamp}"
        else:
            folder_name = f"all_databases_{timestamp}"

        output_dir = os.path.join(OUTPUT_DIR, folder_name)
        error_dbs = []

        try:
            if db_names:
                total_dbs = len(db_names)
                for i, db_name in enumerate(db_names, 1):
                    # Update progress
                    progress = i / total_dbs
                    progress_container.progress(progress, f"Backing up {db_name}...")

                    if show_cancel:
                        if cancel_container.button(
                            "❌ Cancel Backup",
                            key=f"cancel_{timestamp}_{i}",
                            use_container_width=True,
                        ):
                            if os.path.exists(output_dir):
                                shutil.rmtree(output_dir)
                            status_container.info("Backup cancelled")
                            return

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
                        error_dbs.append(db_name)

            else:
                progress_container.progress(0.2, "Backing up all databases...")
                if show_cancel:
                    if cancel_container.button(
                        "❌ Cancel Backup",
                        key=f"cancel_all_{timestamp}",
                        use_container_width=True,
                    ):
                        if os.path.exists(output_dir):
                            shutil.rmtree(output_dir)
                        status_container.info("Backup cancelled")
                        return

                result = subprocess.run(
                    ["mongodump", f"--uri={uri}", f"--out={output_dir}"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise Exception(f"Error creating backup: {result.stderr}")

            # Create zip file
            progress_container.progress(0.9, "Creating ZIP file...")
            zip_filename = f"{output_dir}.zip"
            shutil.make_archive(output_dir, "zip", output_dir)
            shutil.rmtree(output_dir)

            # Clear progress indicators
            progress_container.empty()
            cancel_container.empty()

            success_message = f"""✅ Backup completed! 
                ⚠️ Note: Backup files will be automatically deleted after {BACKUP_RETENTION_HOURS} hour(s)
                """

            if error_dbs:
                success_message += f"\n⚠️ Error backing up {', '.join(error_dbs)}"

            status_container.success(success_message)

            # Offer download
            with open(zip_filename, "rb") as fp:
                total_size = os.path.getsize(zip_filename)
                st.download_button(
                    label=f"📥 Download Backup ZIP ({humanbytes(total_size)})",
                    data=fp,
                    file_name=os.path.basename(zip_filename),
                    mime="application/zip",
                    use_container_width=True,
                )

        except Exception as e:
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            status_container.error(str(e))

    finally:
        # Always clean up the UI elements
        progress_container.empty()
        cancel_container.empty()


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


def validate_backup_zip(zip_path):
    """Validate that the zip file was created by this tool"""
    try:
        # Check if it's a valid zip
        if not zipfile.is_zipfile(zip_path):
            return False, "Invalid ZIP file"

        # Extract and verify structure
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            file_list = zip_ref.namelist()

            # Check if files follow our backup structure
            # Our backups have folders containing dump files
            has_valid_structure = any(
                name.endswith(".bson") or name.endswith(".metadata.json")
                for name in file_list
            )

            if not has_valid_structure:
                return False, "ZIP file does not contain valid MongoDB backup data"

        return True, None

    except Exception as e:
        return False, f"Error validating ZIP file: {str(e)}"


def restore_database(uri, zip_file, db_name):
    """Restore databases from a backup ZIP file"""
    temp_dir = os.path.join(
        OUTPUT_DIR, "temp_restore_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # Save uploaded file
        zip_path = os.path.join(temp_dir, "backup.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_file.getvalue())

        # Validate the zip
        is_valid, error_msg = validate_backup_zip(zip_path)
        if not is_valid:
            st.error(error_msg)
            return

        # Extract zip
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        backup_dirs = [
            d
            for d in os.listdir(temp_dir)
            if os.path.isdir(os.path.join(temp_dir, d)) and d != "__MACOSX"
        ]
        if not backup_dirs:
            st.error("No valid backup directory found in ZIP")
            return

        backup_dir = os.path.join(temp_dir, backup_dirs[0])

        # Show status
        status_text = st.empty()

        # Prepare mongorestore command with new database name
        cmd = ["mongorestore", f"--uri={uri}", f"--db={db_name}", backup_dir]

        # Run mongorestore with status updates
        status_text.text("Restoring databases...")
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )

        # Process output in real-time
        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break

            # Update status text with document count
            if "document" in line:
                status_text.text("Restoring... Please wait")

        # Get final result
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            st.error(f"Error restoring databases: {stderr}")
        else:
            st.success(f"✅ Database restored successfully to '{db_name}'!")

    except Exception as e:
        st.error(f"Error during restore: {str(e)}")
    finally:
        # Cleanup
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


st.title("MongoDB Backup & Restore Tool 💾")
st.caption("Backup and restore your MongoDB databases with ease")


# Privacy Warning
st.warning(
    f"""
⚠️ **Privacy Notice**: 
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

    try:
        client = pymongo.MongoClient(uri)
        databases = client.list_database_names()

        # Replace the columns section with tabs
        tab1, tab2 = st.tabs(["📤 Backup", "📥 Restore"])

        with tab1:
            backup_type = st.radio(
                "Select Backup Type",
                ["Specific Databases", "All Databases"],
                label_visibility="collapsed",
            )

            if backup_type == "Specific Databases":
                selected_dbs = st.multiselect(
                    "Select databases to backup",
                    databases,
                    help="💡 Select multiple databases to backup",
                )

                if st.button("📤 Start Backup", use_container_width=True):
                    if not selected_dbs:
                        st.error("Please select at least one database")
                    else:
                        create_and_offer_download(uri, selected_dbs)

            else:  # All Databases
                st.info("💡 All databases will be backed up")
                if st.button("📤 Backup All Databases", use_container_width=True):
                    create_and_offer_download(uri)

        with tab2:
            st.info(
                """
            💡 **Restore Instructions:**
            1. Only upload ZIP files created by this tool
            2. Enter a database name for restoration
            3. Check Backup tab to see available database names
            4. Ensure sufficient permissions
            """
            )

            uploaded_file = st.file_uploader(
                "Upload backup ZIP file",
                type="zip",
                help="Upload a backup ZIP file created by this tool",
            )

            if uploaded_file:
                new_db_name = st.text_input(
                    "Database Name",
                    placeholder="Enter a database name (new or existing)",
                    help="Enter the database name where you want to restore. If it exists, data will be merged.",
                )

                if new_db_name:
                    st.info(
                        "ℹ️ If this database already exists, the backup will be merged with existing data."
                    )

                if st.button("📥 Start Restore", use_container_width=True):
                    if not new_db_name:
                        st.error("Please enter a database name")
                    else:
                        restore_database(uri, uploaded_file, new_db_name)

    except ConnectionFailure:
        if "localhost" in uri:
            st.info(
                f"""
            ℹ️ Using localhost? You might want to:
            1. [Host MongoDB on Atlas](https://www.mongodb.com/cloud/atlas/register)
            2. [Host this tool yourself]({SOURCE_URL})
            """
            )
        else:
            st.error(
                "Failed to connect to MongoDB. Please check your URI and try again."
            )

# Add footer at the bottom
st.markdown("---")
st.markdown(
    f"""
    <div style="text-align: center; color: #666;">
        Made by <a href="{GITHUB_URL}" target="_blank">Kevin Nadar</a>
    </div>
    """,
    unsafe_allow_html=True,
)
