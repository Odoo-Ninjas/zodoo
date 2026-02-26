#!/bin/bash
SHA="$1"
echo $SHA > /sha
if [[ -z "$SHA" ]]; then
	echo "SHA missing"
	exit -3
fi
