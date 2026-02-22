#!/bin/bash
set -e

echo "Updating system..."
sudo apt-get update && sudo apt-get upgrade -y

echo "Installing Tesseract and Python dependencies..."
sudo apt-get install -y tesseract-ocr python3-pip git docker.io

echo "Setting up CiteLine Worker..."
mkdir -p ~/citeline
cd ~/citeline

# Note: We will need to clone your repo here once it's on GitHub
echo "Worker environment ready."
