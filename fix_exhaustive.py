import sys

with open('ni_measurment.py', 'r') as f:
    lines = f.readlines()

# Find and replace the Phase 2 candidate building section
# Find the line "# Build set of lines that are part of DIRECT WIRE BRIDGES."
# and replace everything through "connected_pairs_for_phase2 = phase2_candidates"

start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if '# Build set of lines that are part of DIRECT WIRE BRIDGES.' in line:
        start_idx = i
    if start_idx is not None and 'connected_pairs_for_phase2 = phase2_candidates' in line:
        end_idx = i + 1
        break

if start_idx is None or end_idx is None:
    print(f"Could not find section: start_idx={start_idx}, end_idx={end_idx}")
    sys.exit(1)

new_block = '''            # Build candidate pairs: ALL pin pairs against ALL outputs,
            # excluding bridged lines whose voltage is forced by their
            # partner (they can't be independent gate inputs/outputs).
            phase2_candidates = []
            for i, line_a in enumerate(dio_all):
                if line_a in bridged_lines:
                    continue
                for line_b in dio_all[i + 1:]:
                    if line_b in bridged_lines:
                        continue
                    phase2_candidates.append((line_a, line_b, None))

            if self.cli_mode:
                print(f"Phase 2: Exhaustive mode — testing ALL {len(phase2_candidates)} pin pairs "
                      f"against all {len(dio_all)} outputs")
                print(f"  Total write/read cycles: {len(phase2_candidates) * 4 * len(dio_all)}")

            connected_pairs_for_phase2 = phase2_candidates
'''

new_lines = lines[:start_idx] + [new_block] + lines[end_idx:]

with open('ni_measurment.py', 'w') as f:
    f.writelines(new_lines)

print("Done!")