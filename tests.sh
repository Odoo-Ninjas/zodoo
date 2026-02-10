#!/bin/bash

odoo init f1 19.0
cd f1
gimera apply
odoo reload
odoo build
odoo -f db reset
odoo up -d
