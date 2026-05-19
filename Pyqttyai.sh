#!/bin/bash
set -x

cd "$HOME/Projetos/pyqttyai"
. .venv/bin/activate
python main.py $@

# find \( -name "v0.*" -o -name ".venv" \) -prune -or -name "*.py" -print0 | sed ':a;N;$!ba;s/\n/\\\\n/;s/\([\\[:blank:]'"'"'"]\)/\\\1/g' | xargs -0 -L 10 | awk '{print "tar cvf chunk_" NR ".tar.py " $0}' | bash
