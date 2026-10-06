#! /bin/bash
# Idempotent (A2-audit 2026-10-06): apt alleen als docker ontbreekt. Elke boot apt draaien
# kostte op 1 GB geheugen en kon docker upgraden terwijl de container start.
if ! command -v docker >/dev/null 2>&1 || ! command -v docker-compose >/dev/null 2>&1; then
  apt-get update
  apt-get install -y docker.io docker-compose
fi
systemctl enable docker
systemctl start docker
