import pandas as pd
import os

filepath = r"d:\방과후 징수 엑셀\방과후 기초자료.xlsx"
output_file = r"d:\방과후 징수 엑셀\inspection_results_base.md"

with open(output_file, "w", encoding="utf-8") as out:
    if not os.path.exists(filepath):
        out.write(f"File not found: {filepath}\n")
    else:
        out.write(f"# File: 방과후 기초자료.xlsx\n")
        try:
            xls = pd.ExcelFile(filepath)
            out.write(f"**Sheets:** {xls.sheet_names}\n\n")
            
            for sheet in xls.sheet_names:
                out.write(f"## Sheet: {sheet}\n")
                df = pd.read_excel(filepath, sheet_name=sheet, nrows=10)
                out.write("### Columns:\n")
                out.write(str(df.columns.tolist()) + "\n\n")
                out.write("### First 10 rows:\n")
                out.write("```csv\n")
                out.write(df.head(10).to_csv(index=False))
                out.write("```\n\n")
                
        except Exception as e:
            out.write(f"Error reading file: {e}\n")
