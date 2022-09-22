#!/bin/bash

eval "$(pdm --pep582)"
exec python3 runexp.py /bundle -l 0.0.0.0 $@
