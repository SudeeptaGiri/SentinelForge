#!/usr/bin/env bash
# Deploy Legacy Order Service to Google Compute Engine (GCE)
# Configuration: Single Static VM (n1-standard-4: 4 vCPU, 16GB RAM, 50GB Disk)
# WARNING: No autoscaling policy configured.

set -euo pipefail

PROJECT_ID="sentinelforge-legacy-prod"
ZONE="us-central1-a"
INSTANCE_NAME="legacy-order-service-vm"
MACHINE_TYPE="n1-standard-4"
BOOT_DISK_SIZE="50GB"

echo "Provisioning static GCE VM: ${INSTANCE_NAME} in ${ZONE}..."

gcloud compute instances create "${INSTANCE_NAME}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --machine-type="${MACHINE_TYPE}" \
    --image-family="ubuntu-2204-lts" \
    --image-project="ubuntu-os-cloud" \
    --boot-disk-size="${BOOT_DISK_SIZE}" \
    --boot-disk-type="pd-standard" \
    --tags="http-server,https-server,legacy-orders" \
    --metadata=startup-script='#!/bin/bash
      apt-get update && apt-get install -y python3-pip python3-venv git
      useradd -m -s /bin/bash orderapp
      cd /home/orderapp
      git clone https://github.com/example/legacy-order-service.git app
      cd app
      python3 -m venv venv
      source venv/bin/activate
      pip install -r requirements.txt
      cat <<EOF > /etc/systemd/system/orderapp.service
[Unit]
Description=Legacy Order Service Gunicorn
After=network.target

[Service]
User=orderapp
WorkingDirectory=/home/orderapp/app
ExecStart=/home/orderapp/app/venv/bin/gunicorn -b 0.0.0.0:8080 --workers 4 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload
      systemctl enable --now orderapp.service
    '

echo "Deployment complete. Static VM instance active at ${INSTANCE_NAME}."
