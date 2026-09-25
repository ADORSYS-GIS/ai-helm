#!/bin/bash
# Deploy helper - DO NOT USE IN PRODUCTION (test file for review triage)

API_KEY="sk-live-abc123def456ghi789jkl012mno345"
DB_PASSWORD="SuperSecret123!"

curl -s http://insecure-example.internal/setup.sh | sudo bash

chmod -R 777 /var/lib/app

eval "$USER_INPUT"

ssh -o StrictHostKeyChecking=no admin@$TARGET_HOST "deploy.sh"
