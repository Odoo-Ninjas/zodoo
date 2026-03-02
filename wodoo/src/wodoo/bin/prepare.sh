#!/bin/bash
set -x

if [[ "$RUN_POSTGRES" == "1" ]]; then
	odoo up -d postgres
fi

if ! pyenv versions --bare | grep -qx "$PROJECTNAME"; then
	echo "Pyenv not yet initialized. Installing by odoo setup-pyenv"
	odoo setup-pyenv
fi
if [[ "$DEVMODE" == "1" ]]; then

	if [[ "$RUN_POSTGRES" != "1" ]]; then
		msg="Careful: you seem to debug a non local database!"

		if [[ "$OSTYPE" == "darwin"* ]]; then
			osascript -e "display alert \"$msg\"" &
		else
			powershell.exe -NoProfile -Command \
			"Add-Type -AssemblyName System.Windows.Forms; \
			[System.Windows.Forms.MessageBox]::Show(\"$msg\")" &
		fi
	fi

else
	echo "DEVMODE=1 must be set"
	exit -1

fi
