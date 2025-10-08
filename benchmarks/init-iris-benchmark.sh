#!/bin/bash
# Initialize IRIS for benchmark: just merge CPF

set -e

echo "Merging CPF..."
iris merge IRIS /app/merge.cpf

echo "IRIS benchmark initialization complete!"
