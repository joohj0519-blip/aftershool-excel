import os

with open("app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Replace json files to use get_monthly_path
json_files = ["merged_students.json", "programs.json", "enrollments.json", "program_fees.json", "instructor_fees.json", "student_refunds.json"]

for jf in json_files:
    # load_data
    code = code.replace(f'load_data("{jf}"', f'load_data(get_monthly_path("{jf}")')
    # save_data
    code = code.replace(f'save_data("{jf}"', f'save_data(get_monthly_path("{jf}")')
    # os.path.exists
    code = code.replace(f'os.path.exists("{jf}")', f'os.path.exists(get_monthly_path("{jf}"))')

# Replace hardcoded month variables
code = code.replace("m = 3 # 3월 기준", "m = st.session_state.selected_month")
code = code.replace('"3월 시수"', 'f"{m}월 시수"')
code = code.replace('"3월 예정 차시"', 'f"{m}월 예정 차시"')

# In tab 3 and 4, we have dictionaries that might use "3월 시수" or "3월 예정 차시". 
# The f-string replacement will handle them if they are inside dictionaries. But wait, column_config uses "3월 시수" string literal directly.
# Let's fix column configs dynamically:
code = code.replace('"3월 시수": st.column_config.NumberColumn', 'f"{m}월 시수": st.column_config.NumberColumn')
code = code.replace('"3월 예정 차시": st.column_config.NumberColumn', 'f"{m}월 예정 차시": st.column_config.NumberColumn')

# Write back
with open("app.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Done.")
