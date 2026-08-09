#!/bin/bash
SHA="$1"
if [[ -z "$SHA" ]]; then
	# SHA enforcement disabled (e.g. SHA_IN_DOCKER=0 / base-split dev build
	# where the composer does not inject CUSTOMS_SHA). Don't hard-fail.
	SHA="n/a"
fi
echo $SHA > /sha
