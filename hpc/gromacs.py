"""
CGflow code library.

Developed by: Ji Wenke
Date: 2026.05.06

Renders LSF submit scripts for GROMACS jobs from a small set of queue and command settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class LsfScriptBuilder:
    """Build a readable LSF script, mainly for GROMACS jobs."""

    lsfname: str = "submit.lsf"
    jobname: str = "run"
    ncores: int = 64
    nhour: int = 24
    qname: str = "standard"
    group: str = "cadmol"
    app: str = "gromacs"
    mpi: str = "intelmpi"
    gmx_module: str = "gromacs/2022.4"
    commands: list[str] = field(default_factory=list)
    stdout_name: str = "%J.out"
    stderr_name: str = "%J.err"

    def set_commands(self, commands: Iterable[str]) -> None:
        self.commands = list(commands)

    def render(self) -> str:
        command_block = "\n".join(self.commands)
        if command_block:
            command_block += "\n"

        return f"""#!/bin/bash -x
#BSUB -J {self.jobname}
#BSUB -n {self.ncores}
#BSUB -q {self.qname}
#BSUB -G {self.group}
#BSUB -W {self.nhour}:00
#BSUB -app {self.app}
#BSUB -a {self.mpi}
#BSUB -o {self.stdout_name}
#BSUB -e {self.stderr_name}

sleep 15
source /etc/profile.d/modules.sh
module load {self.gmx_module}

OLD_DIR=$PWD
export OMP_NUM_THREADS=$LSB_DJOB_NUMPROC

write_running_timing() {{
cat > "$TIMING_FILE" <<EOF
{{
  "job_id": "${{LSB_JOBID:-unknown}}",
  "status": "running",
  "start_time": "$START_TIME_UTC",
  "end_time": null,
  "runtime_seconds": null,
  "exit_code": null
}}
EOF
}}

write_finished_timing() {{
cat > "$TIMING_FILE" <<EOF
{{
  "job_id": "${{LSB_JOBID:-unknown}}",
  "status": "$RUN_STATUS",
  "start_time": "$START_TIME_UTC",
  "end_time": "$END_TIME_UTC",
  "runtime_seconds": $RUNTIME_SECONDS,
  "exit_code": $RUN_EXIT_CODE
}}
EOF
}}

# Submitted input files are uploaded into the submission folder first, while
# GROMACS actually runs inside ``$WORK_DIR`` on the compute node. Copy the
# flat input files over before switching directories.
find . -maxdepth 1 -type f -exec cp {{}} "$WORK_DIR"/ \\;

cd "$WORK_DIR" || exit 1
TIMING_FILE="$WORK_DIR/job_timing.json"
# Now run GROMACS
START_TIME_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
START_TIME_EPOCH=$(date +%s)
write_running_timing

RUN_EXIT_CODE=0
{{
{command_block}}} || RUN_EXIT_CODE=$?

END_TIME_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
END_TIME_EPOCH=$(date +%s)
RUNTIME_SECONDS=$((END_TIME_EPOCH - START_TIME_EPOCH))
if [ "$RUN_EXIT_CODE" -eq 0 ]; then
  RUN_STATUS="finished"
else
  RUN_STATUS="failed"
fi
write_finished_timing

if [ "$RUN_EXIT_CODE" -ne 0 ]; then
  exit "$RUN_EXIT_CODE"
fi

echo "Collecting results..."
tar cvf "$OLD_DIR/$LSB_JOBID.results.tar" *
exit
"""

    def dump(self, filename: str | Path | None = None) -> Path:
        target = Path(filename or self.lsfname)
        target.write_text(self.render())
        return target
