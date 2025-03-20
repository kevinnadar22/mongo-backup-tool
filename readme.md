
# MongoDB Backup & Restore Tool 💾

A simple web tool to backup and restore MongoDB databases.

## Features
- 🔄 Backup specific or all databases
- 📦 Restore databases with ease

## Quick Start

### Manual Setup

1. Clone the repository:
```bash
git clone https://github.com/kevinnadar22/mongo-backup-tool.git
cd mongodb-backup-tool
```

2. Install requirements:
```bash
# Install MongoDB Tools
## Ubuntu/Debian
sudo apt-get install mongodb-database-tools

## macOS
brew install mongodb/brew/mongodb-database-tools

## Windows
# Download from https://www.mongodb.com/try/download/database-tools

# Install Python dependencies
pip install -r requirements.txt
```

3. Run the app:
```bash
streamlit run main.py
```

## Docker Deployment

1. Build the image:
```bash
docker build -t mongo-backup-tool .
```

2. Run container:
```bash
docker run -p 8501:8501 mongo-backup-tool
```

## Environment Variables
- `MAX_EXPORT_SIZE`: Maximum backup size in bytes (default: 512MB)
- `BACKUP_RETENTION_HOURS`: Hours to keep backups (default: 1)


## Author
- [Kevin Nadar](https://github.com/kevinnadar22)
