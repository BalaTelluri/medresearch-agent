import argparse,json
from pathlib import Path
from genomics.core import interpret
p=argparse.ArgumentParser(description='Research-only GRCh38 variant evidence')
p.add_argument('input',nargs='?',default=str(Path(__file__).parent/'demo.vcf'))
p.add_argument('--no-literature',action='store_true');p.add_argument('--output')
a=p.parse_args();source=Path(a.input);text=source.read_text() if source.is_file() else a.input
result=json.dumps(interpret(text,literature=not a.no_literature),indent=2)
if a.output: Path(a.output).write_text(result)
else: print(result)
