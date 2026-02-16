import glob
import os

# Define paths
source_dir = r"backend/batch_audit_outputs/csv_exports"
output_file = r"backend/batch_audit_outputs/merged_first_10_rows.csv"

# Get all CSV files
files = glob.glob(os.path.join(source_dir, "*.csv"))
print(f"Found {len(files)} files to merge.")

# Open output file
with open(output_file, 'w', encoding='utf-8') as outfile:
    for i, file in enumerate(files):
        try:
            with open(file, 'r', encoding='utf-8') as infile:
                # Read first 10 lines
                lines = []
                for _ in range(10):
                    line = infile.readline()
                    if not line:
                        break
                    lines.append(line)
                
                # Write to output
                outfile.writelines(lines)
                
                # Add a separator for readability between files
                outfile.write("\n" + "-"*30 + "\n\n")
                
        except Exception as e:
            print(f"Error reading {file}: {e}")

print(f"Successfully merged {len(files)} files into {output_file}")
