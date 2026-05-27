import re

def inject_logic():
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Add calculate_retroactive_adjustments function at the top level
    calc_func = """
def calculate_retroactive_adjustments(current_m, current_y, settings):
    months_seq = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]
    try:
        curr_idx = months_seq.index(current_m)
    except ValueError:
        return {}
    
    if curr_idx == 0:
        return {} 
        
    retro_data = {}
    import os
    import pandas as pd
    
    curr_folder = f"data/{current_y}_{current_m:02d}"
    curr_stud = pd.DataFrame(load_data(os.path.join(curr_folder, "merged_students.json"), []))
    if curr_stud.empty:
        return {}
        
    curr_qual = {}
    for _, r in curr_stud.iterrows():
        k = (str(r.get("학년","")), str(r.get("반","")), str(r.get("이름","")))
        curr_qual[k] = str(r.get("가구자격", "수익자"))
        
    for past_idx in range(curr_idx):
        pm = months_seq[past_idx]
        py = settings["year"] if pm >= 3 else settings["year"] + 1
        past_folder = f"data/{py}_{pm:02d}"
        
        if not os.path.exists(past_folder):
            continue
            
        p_enroll = pd.DataFrame(load_data(os.path.join(past_folder, "enrollments.json"), []))
        p_prog_fees = pd.DataFrame(load_data(os.path.join(past_folder, "program_fees.json"), []))
        p_stud = pd.DataFrame(load_data(os.path.join(past_folder, "merged_students.json"), []))
        p_refunds = load_data(os.path.join(past_folder, "student_refunds.json"), {})
        
        if p_enroll.empty or p_prog_fees.empty or p_stud.empty:
            continue
            
        p_enroll.columns = p_enroll.columns.astype(str).str.strip()
        if "프로그램" in p_enroll.columns:
            melted = p_enroll.rename(columns={"프로그램": "프로그램명"}).copy()
        elif "프로그램명" in p_enroll.columns:
            melted = p_enroll.copy()
        else:
            id_vars = [c for c in p_enroll.columns if c in ["학년", "반", "번호", "이름"]]
            melted = p_enroll.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
            melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
            
        if melted.empty:
            continue
            
        melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
        p_prog_fees["프로그램명"] = p_prog_fees["프로그램명"].astype(str).str.strip()
        
        p_calc = pd.merge(melted, p_prog_fees[["프로그램명", "최종 수강료", "월 재료비"]], on="프로그램명", how="inner")
        merge_keys = [k for k in ["학년", "반", "이름"] if k in p_stud.columns and k in melted.columns]
        if merge_keys:
            p_calc = pd.merge(p_calc, p_stud, on=merge_keys, how="left")
        else:
            p_calc["가구자격"] = "수익자"
            
        p_calc["고유ID"] = p_calc["학년"].astype(str) + "-" + p_calc["반"].astype(str) + "-" + p_calc["이름"] + "_" + p_calc["프로그램명"]
        
        for _, r in p_calc.iterrows():
            fee = r.get("최종 수강료", 0)
            mat = r.get("월 재료비", 0)
            if pd.isna(fee): fee = 0
            if pd.isna(mat): mat = 0
            
            p_qual = str(r.get("가구자격", "수익자")).strip()
            if p_qual == "" or p_qual == "nan": p_qual = "수익자"
            
            k = (str(r.get("학년","")), str(r.get("반","")), str(r.get("이름","")))
            c_qual = curr_qual.get(k, p_qual).strip()
            if c_qual == "" or c_qual == "nan": c_qual = "수익자"
            
            if p_qual == c_qual:
                continue
                
            uid = r["고유ID"]
            refund_info = p_refunds.get(uid, {})
            refund_amt = refund_info.get("환급액", 0)
            
            total = fee + mat
            # 과거 청구액 (당시 자격 기준)
            if p_qual == "교육비지원":
                p_charge = 0
                p_mat_charge = 0
            else:
                p_charge = total
                p_mat_charge = mat
            p_final_charge = max(p_mat_charge, p_charge - refund_amt)
            
            # 제대로 청구했어야 할 액수 (현재 자격 기준)
            if c_qual == "교육비지원":
                c_charge = 0
                c_mat_charge = 0
            else:
                c_charge = total
                c_mat_charge = mat
            c_final_charge = max(c_mat_charge, c_charge - refund_amt)
            
            diff = c_final_charge - p_final_charge
            if diff != 0:
                if uid not in retro_data:
                    retro_data[uid] = {"추가징수액": 0, "소급환급액": 0}
                if diff > 0:
                    retro_data[uid]["추가징수액"] += diff
                else:
                    retro_data[uid]["소급환급액"] += abs(diff)
                    
    return retro_data
"""
    # Insert calc_func right after def to_excel(df): if we can, or just after the imports
    # Let's insert before def to_excel
    if "def calculate_retroactive_adjustments" not in content:
        content = content.replace("def to_excel(df):", calc_func + "\ndef to_excel(df):")

    # 2. Add UI for the button
    ui_block = """        st.markdown("---")
        st.subheader("🧑‍🎓 학생별 수강료 정산 명세 및 소급 정산")
        
        with st.expander("🔄 자격 변동에 따른 과거 월 소급 정산액 계산기", expanded=False):
            st.info("이 버튼을 누르면 현재 월 이전에 정산되었던 내역과 현재 자격을 비교하여 **추가 징수액**과 **소급 환급액**을 자동 계산합니다.")
            if st.button("계산 실행 및 적용"):
                retro_res = calculate_retroactive_adjustments(m, current_year, settings)
                save_data(get_monthly_path("retroactive_adjustments.json"), retro_res)
                st.success("✅ 자격 변동에 따른 소급 정산 내역이 계산되어 적용되었습니다!")
                st.rerun()
"""
    content = content.replace('        st.markdown("---")\n        st.subheader("🧑‍🎓 학생별 수강료 정산 명세")', ui_block)

    # 3. Update the calculation logic in calc_fees
    calc_old = """                    # 환급 내역 불러오기
                    refunds_data = load_data(get_monthly_path("student_refunds.json"), {})
                    
                    # 징수액 계산
                    def calc_fees(row):
                        fee = row.get("최종 수강료", 0)
                        mat = row.get("월 재료비", 0)
                        qual = str(row.get("가구자격", ""))
                        
                        total = fee + mat
                        if qual == "교육비지원":
                            support = total
                            charge = 0
                            mat_charge = 0
                        else:
                            support = 0
                            charge = total
                            mat_charge = mat
                            
                        uid = row["고유ID"]
                        refund_info = refunds_data.get(uid, {})
                        refund_amt = refund_info.get("환급액", 0)
                        refund_reason = refund_info.get("환급사유", "")
                        
                        # 재료비는 환급되지 않으므로, 환급 후 최종 징수액은 최소 재료비(mat_charge) 이상이어야 함
                        final_charge = max(mat_charge, charge - refund_amt)
                            
                        return pd.Series([total, support, charge, refund_amt, refund_reason, final_charge])
                        
                    df_calc[["총 금액", "지원금(면제)", "기본 징수액", "환급액", "환급사유", "최종 징수액"]] = df_calc.apply(calc_fees, axis=1)
                    
                    display_cols = ["고유ID", "학년", "반", "이름", "프로그램명", "강사명", "운영요일", f"{m}월 시수", "차시당 단가", "가구자격", "총 금액", "지원금(면제)", "기본 징수액", "환급액", "환급사유", "최종 징수액"]"""
    
    calc_new = """                    # 환급 내역 및 소급 정산 내역 불러오기
                    refunds_data = load_data(get_monthly_path("student_refunds.json"), {})
                    retro_data = load_data(get_monthly_path("retroactive_adjustments.json"), {})
                    
                    # 징수액 계산
                    def calc_fees(row):
                        fee = row.get("최종 수강료", 0)
                        mat = row.get("월 재료비", 0)
                        qual = str(row.get("가구자격", ""))
                        
                        total = fee + mat
                        if qual == "교육비지원":
                            support = total
                            charge = 0
                            mat_charge = 0
                        else:
                            support = 0
                            charge = total
                            mat_charge = mat
                            
                        uid = row["고유ID"]
                        refund_info = refunds_data.get(uid, {})
                        refund_amt = refund_info.get("환급액", 0)
                        refund_reason = refund_info.get("환급사유", "")
                        
                        retro_info = retro_data.get(uid, {})
                        retro_add = retro_info.get("추가징수액", 0)
                        retro_sub = retro_info.get("소급환급액", 0)
                        
                        # 재료비는 환급되지 않으므로 기본 징수액에 한도 적용
                        base_final = max(mat_charge, charge - refund_amt)
                        
                        # 최종 징수액 = (기본징수액 - 일반환급액) + 소급추가징수액 - 소급환급액
                        final_charge = base_final + retro_add - retro_sub
                            
                        return pd.Series([total, support, charge, retro_add, retro_sub, refund_amt, refund_reason, final_charge])
                        
                    df_calc[["총 금액", "지원금(면제)", "기본 징수액", "추가징수액", "소급환급액", "환급액", "환급사유", "최종 징수액"]] = df_calc.apply(calc_fees, axis=1)
                    
                    display_cols = ["고유ID", "학년", "반", "이름", "프로그램명", "강사명", "운영요일", f"{m}월 시수", "차시당 단가", "가구자격", "총 금액", "지원금(면제)", "기본 징수액", "추가징수액", "소급환급액", "환급액", "환급사유", "최종 징수액"]"""
                    
    content = content.replace(calc_old, calc_new)

    # 4. Update UI summary
    summary_old = """                        total_charge = df_display["기본 징수액"].sum()
                        total_support = df_display["지원금(면제)"].sum()
                        total_refund = df_display["환급액"].sum()
                        final_total = df_display["최종 징수액"].sum()
                        
                        with col_summary:
                            st.info(f"💡 **현재 조회된 합계** | 기본 징수액: **{total_charge:,.0f}원** | 환급 총액: **{total_refund:,.0f}원** | 최종 징수액: **{final_total:,.0f}원**")"""
                            
    summary_new = """                        total_charge = df_display["기본 징수액"].sum()
                        total_support = df_display["지원금(면제)"].sum()
                        total_retro_add = df_display["추가징수액"].sum()
                        total_retro_sub = df_display["소급환급액"].sum()
                        total_refund = df_display["환급액"].sum()
                        final_total = df_display["최종 징수액"].sum()
                        
                        with col_summary:
                            st.info(f"💡 **합계** | 기본: **{total_charge:,.0f}원** | 환급: **{total_refund:,.0f}원** | 소급추가: **{total_retro_add:,.0f}원** | 소급환급: **{total_retro_sub:,.0f}원** | 최종 징수: **{final_total:,.0f}원**")"""

    content = content.replace(summary_old, summary_new)
    
    # 5. Update dataframe editor columns
    editor_cols_old = """                                "총 금액": st.column_config.NumberColumn(disabled=True),
                                "지원금(면제)": st.column_config.NumberColumn(disabled=True),
                                "기본 징수액": st.column_config.NumberColumn(disabled=True),
                                "환급액": st.column_config.NumberColumn("일반 환급액", min_value=0),
                                "환급사유": st.column_config.TextColumn("환급 사유"),
                                "최종 징수액": st.column_config.NumberColumn("최종 징수액", disabled=True)"""
    
    editor_cols_new = """                                "총 금액": st.column_config.NumberColumn(disabled=True),
                                "지원금(면제)": st.column_config.NumberColumn(disabled=True),
                                "기본 징수액": st.column_config.NumberColumn(disabled=True),
                                "추가징수액": st.column_config.NumberColumn("소급 추가징수", disabled=True),
                                "소급환급액": st.column_config.NumberColumn("소급 환급액", disabled=True),
                                "환급액": st.column_config.NumberColumn("일반 환급액(결석등)", min_value=0),
                                "환급사유": st.column_config.TextColumn("환급 사유"),
                                "최종 징수액": st.column_config.NumberColumn("최종 징수액", disabled=True)"""
                                
    content = content.replace(editor_cols_old, editor_cols_new)

    with open("app.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    inject_logic()
    print("Injected!")
