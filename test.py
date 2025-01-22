import os
import subprocess
import streamlit as st

# Function to install MongoDB tools
def install_mongodb_tools():
    try:
        # Install MongoDB tools using apt (Linux)
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "install", "-y", "mongodb-database-tools"], check=True)
        st.success("MongoDB tools installed successfully.")
    except Exception as e:
        st.error(f"Failed to install MongoDB tools: {e}")

# Check and install tools during app startup
if st.button("Install MongoDB Tools"):
    install_mongodb_tools()
