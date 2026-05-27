def move_block():
    with open("app.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    # Find start
    for i, line in enumerate(lines):
        if "col_hdr1, col_hdr2 = st.columns([1, 1])" in line and "과거 월 소급 정산액 계산" in lines[i+2]:
            start_idx = i
            break
            
    if start_idx == -1:
        print("Could not find start index")
        return
        
    # Find end
    for i in range(start_idx, len(lines)):
        if 'st.markdown("<br>", unsafe_allow_html=True)' in lines[i]:
            end_idx = i
            break
            
    if end_idx == -1:
        print("Could not find end index")
        return
        
    print(f"Moving lines {start_idx} to {end_idx}")
    
    # Extract the block
    block = lines[start_idx:end_idx+1]
    
    # Delete the block from original position
    del lines[start_idx:end_idx+1]
    
    # Find where to insert (before "with tab4:")
    insert_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("with tab4:"):
            insert_idx = i
            break
            
    if insert_idx == -1:
        print("Could not find insert index")
        return
        
    # We want to insert it inside the else block of tab3, so we check indentation.
    # Actually, we can just insert it at insert_idx. But wait, tab4 has no indentation.
    # The else block for programs.json has 4 spaces.
    # Let's insert a divider and the block with 8 spaces indentation.
    # Wait, the block already has 8 spaces indentation.
    # We should insert it just before 'with tab4:' but maybe inside the else?
    # Let's just put it before 'with tab4:' and ensure the indentation is correct.
    # The block's original indentation is 8 spaces.
    
    # Let's add a divider before it.
    block.insert(0, '        st.markdown("---")\n')
    
    lines = lines[:insert_idx] + ["\n"] + block + ["\n"] + lines[insert_idx:]
    
    with open("app.py", "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    print("Done moving block.")

if __name__ == "__main__":
    move_block()
