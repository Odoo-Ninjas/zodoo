#!/bin/bash

if [[ "$RUN_POSTGRES" == "1" ]]; then
	odoo up -d postgres
fi

if [[ "$DEVMODE" != "1" ]]; then

	if [[ "$RUN_POSTGRES" != "1" || -n "$(git status --porcelain)" ]]; then
		msg="Careful: you seem to debug a non local database!"
		if [[ "$OSTYPE" == "darwin"* ]]; then
			osascript -e "display alert \"$msg\""
		else
			powershell.exe -Command \
			"Add-Type -AssemblyName System.Windows.Forms; \
			[System.Windows.Forms.MessageBox]::Show('$msg')"
		fi
	fi

fi
