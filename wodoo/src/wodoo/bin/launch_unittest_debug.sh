#!/bin/bash
set -x

current_dir=$(dirname "$0")
/bin/bash ${current_dir}/prepare.sh

if [[ "$RUN_POSTGRES" == "1" ]]; then
	odoo up -d postgres
fi
