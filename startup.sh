#!/bin/bash
# Azure App Service startup script
gunicorn --bind 0.0.0.0:$PORT --worker-class eventlet -w 1 --timeout 600 app:app