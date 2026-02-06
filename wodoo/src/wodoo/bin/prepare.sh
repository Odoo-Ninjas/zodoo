#!/bin/bash

if [[ "$RUN_POSTGRES" == "1" ]]; then
	odoo up -d postgres
fi
