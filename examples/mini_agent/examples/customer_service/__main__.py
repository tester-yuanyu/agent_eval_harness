import argparse

from .agent import CustomerServiceAgent

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
args = parser.parse_args()
print(CustomerServiceAgent().run(args.input).model_dump_json())
