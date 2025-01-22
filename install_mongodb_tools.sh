#!/bin/bash

# Function to detect OS
get_os() {
    case "$(uname -s)" in
        Linux*)     
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                echo "$ID"
            else
                echo "linux"
            fi
            ;;
        Darwin*)    echo "macos";;
        CYGWIN*)   echo "windows";;
        MINGW*)    echo "windows";;
        *)         echo "unknown";;
    esac
}

# Get OS
OS=$(get_os)

# Install MongoDB tools based on OS
case $OS in
    "ubuntu"|"debian"|"linux")
        echo "Installing MongoDB tools for Ubuntu/Debian..."
        wget -qO - https://www.mongodb.org/static/pgp/server-6.0.asc | sudo apt-key add -
        echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/6.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list
        sudo apt-get update
        sudo apt-get install -y mongodb-database-tools
        ;;
    "macos")
        echo "Installing MongoDB tools for macOS..."
        brew tap mongodb/brew
        brew install mongodb-database-tools
        ;;
    "windows")
        echo "Please download and install MongoDB tools manually from:"
        echo "https://www.mongodb.com/try/download/database-tools"
        exit 1
        ;;
    *)
        echo "Unsupported operating system"
        exit 1
        ;;
esac

# Verify installation
if command -v mongodump >/dev/null 2>&1; then
    echo "MongoDB tools installed successfully!"
    exit 0
else
    echo "Installation failed. Please install manually."
    exit 1
fi 