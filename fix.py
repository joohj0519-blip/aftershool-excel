import os

# The missing block
missing_block = """                "프로그램명": st.column_config.TextColumn(disabled=True),
                "강사구분": st.column_config.TextColumn(disabled=True),
                "운영요일": st.column_config.TextColumn(disabled=True),
                f"{m}월 예정 차시": st.column_config.NumberColumn(disabled=True),
                "차시당 단가": st.column_config.NumberColumn("차시당 단가(원)", disabled=True),
                "총 강사료(예상)": st.column_config.NumberColumn("총 강사료(계산됨, 원)", disabled=True),
                "교육비지원대상 총액": st.column_config.NumberColumn("교육비지원 총액(원)", disabled=True),
                "수익자 부담액": st.column_config.NumberColumn("수익자 부담액(원)", disabled=True),
                "총 수강료 수입": st.column_config.NumberColumn("총 수강료 수입(원)", disabled=True),
                "강사료 보전금": st.column_config.NumberColumn("강사료 보전금(원)", disabled=True),
                "실제 수업 차시": st.column_config.NumberColumn("실제 수업 차시", min_value=0),
                "비고(보강/결강 등)": st.column_config.TextColumn("비고(보강/결강 등)")
            },
            hide_index=True,
            use_container_width=True
        )
        
        col_dl, col_save = st.columns([1, 1])
        with col_dl:
            st.download_button("📥 강사료 정산 명세 엑셀 다운로드", data=to_excel(edited_inst), file_name="강사료_정산명세.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_inst_1")
        with col_save:
            if st.button("✅ 강사료 정산 및 보전금 내역 저장", type="primary"):
                # 합계 행 제외 후 저장
                df_to_save = edited_inst[edited_inst["강사명"] != "합계"].copy()
                
                # Recalculate just in case
                df_to_save["총 강사료(예상)"] = df_to_save["실제 수업 차시"] * df_to_save["차시당 단가"]
                df_to_save["교육비지원대상 총액"] = df_to_save["프로그램명"].map(program_support).fillna(0)
                df_to_save["수익자 부담액"] = df_to_save["프로그램명"].map(program_charge).fillna(0)
                df_to_save["총 수강료 수입"] = df_to_save["프로그램명"].map(program_incomes).fillna(0)
                df_to_save["강사료 보전금"] = (df_to_save["총 강사료(예상)"] - df_to_save["총 수강료 수입"]).apply(lambda x: max(0, x))
                
                save_data(get_monthly_path("instructor_fees.json"), df_to_save.to_dict(orient="records"))
                st.success("✅ 강사별 정산 및 보전금 내역이 성공적으로 저장되었습니다!")
                st.rerun()
            
        st.markdown("---")
        
        # 저장 전이라도 실시간으로 편집된 데이터 기반으로 요약 표시
        df_for_summary = edited_inst[edited_inst["강사명"] != "합계"].copy()
        if not df_for_summary.empty:
            st.subheader("📊 전체 항목별 총합계 (소계)")
            
            # 실시간 재계산
            df_for_summary["총 강사료(예상)"] = df_for_summary["실제 수업 차시"] * df_for_summary["차시당 단가"]
            df_for_summary["교육비지원대상 총액"] = df_for_summary["프로그램명"].map(program_support).fillna(0)
            df_for_summary["수익자 부담액"] = df_for_summary["프로그램명"].map(program_charge).fillna(0)
            df_for_summary["총 수강료 수입"] = df_for_summary["프로그램명"].map(program_incomes).fillna(0)
            df_for_summary["강사료 보전금"] = (df_for_summary["총 강사료(예상)"] - df_for_summary["총 수강료 수입"]).apply(lambda x: max(0, x))
            
            total_inst = len(df_for_summary)
            total_fee = df_for_summary["총 강사료(예상)"].sum()
            total_income = df_for_summary["총 수강료 수입"].sum()
            total_subsidy = df_for_summary["강사료 보전금"].sum()
            total_support = df_for_summary["교육비지원대상 총액"].sum()
            total_charge = df_for_summary["수익자 부담액"].sum()
            int_fee = df_for_summary[df_for_summary["강사구분"] == "내부"]["총 강사료(예상)"].sum()
            ext_fee = df_for_summary[df_for_summary["강사구분"] == "외부"]["총 강사료(예상)"].sum()
            
            st.markdown("##### 📥 이번 달 총 수입 및 보전금")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1. 총 수익자 부담액", f"{total_charge:,.0f} 원")
            c2.metric("2. 총 교육비지원액", f"{total_support:,.0f} 원")
            c3.metric("3. 전체 수강료 수입 (1+2)", f"{total_income:,.0f} 원")
            c4.metric("4. 교육청 강사료 보전금 사용", f"{total_subsidy:,.0f} 원")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            st.markdown("##### 💸 이번 달 강사료 총 지출")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("정산 대상 프로그램", f"{total_inst} 개")
            d2.metric("최종 강사료 총액 (3+4)", f"{total_fee:,.0f} 원")
            d3.metric("ㄴ 내부강사 지급액", f"{int_fee:,.0f} 원")
            d4.metric("ㄴ 외부강사 지급액", f"{ext_fee:,.0f} 원")

with tab5:
    st.header("📈 5. 월간 정산 통계 보고서")
    
    if os.path.exists(get_monthly_path("instructor_fees.json")):
        df_stats = pd.DataFrame(load_data(get_monthly_path("instructor_fees.json"), []))
        if not df_stats.empty:
            st.subheader("📊 프로그램별 수입 및 지출 요약")
            
            # Select columns for report
            report_cols = [
                "프로그램명", "강사명", "강사구분", "총 수강료 수입", 
                "교육비지원대상 총액", "수익자 부담액", "총 강사료(예상)", "강사료 보전금"
            ]
            df_report = df_stats[[c for c in report_cols if c in df_stats.columns]].copy()
            
            st.dataframe(
                df_report,
                column_config={
                    "프로그램명": st.column_config.TextColumn("프로그램명"),
                    "강사명": st.column_config.TextColumn("강사명"),
                    "강사구분": st.column_config.TextColumn("강사구분"),
                    "총 수강료 수입": st.column_config.NumberColumn("전체 수강료 수입(원)"),
                    "교육비지원대상 총액": st.column_config.NumberColumn("교육비지원 총액(원)"),
                    "수익자 부담액": st.column_config.NumberColumn("수익자 부담액(원)"),
                    "총 강사료(예상)": st.column_config.NumberColumn("최종 강사료 지출(원)"),
                    "강사료 보전금": st.column_config.NumberColumn("교육청 보전금 사용(원)")
                },
                use_container_width=True, 
                hide_index=True
            )
            st.download_button("📥 프로그램별 통계 엑셀 다운로드", data=to_excel(df_report), file_name="월간_프로그램별_통계.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stat_1")
            
            st.markdown("---")
            st.subheader("👥 강사 구분별(내/외부) 요약")
            if "강사구분" in df_stats.columns:
                df_grp = df_stats.groupby("강사구분").agg({
                    "프로그램명": "count",
                    "총 수강료 수입": "sum",
                    "수익자 부담액": "sum",
                    "총 강사료(예상)": "sum",
                    "강사료 보전금": "sum"
                }).reset_index()
                df_grp.rename(columns={"프로그램명": "운영 프로그램 수", "총 강사료(예상)": "강사료 지출 총액"}, inplace=True)
                
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.dataframe(
                        df_grp,
                        column_config={
                            "강사구분": "강사 구분",
                            "운영 프로그램 수": st.column_config.NumberColumn("프로그램 수(개)"),
                            "총 수강료 수입": st.column_config.NumberColumn("수강료 수입 합계(원)"),
                            "수익자 부담액": st.column_config.NumberColumn("수익자 부담금 합계(원)"),
                            "강사료 지출 총액": st.column_config.NumberColumn("강사료 지출 합계(원)"),
                            "강사료 보전금": st.column_config.NumberColumn("보전금 사용 합계(원)"),
                        },
                        use_container_width=True, 
                        hide_index=True
                    )
            
            st.markdown("---")
            st.subheader("💰 재원별 수입/지출 종합 통계 (전체 누적)")
            
            try:
                months_list = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]
                month_names = [f"{x}월" for x in months_list]
                
                fund_categories = {}
                
                def add_fund(category, m_name, amount):
                    if category not in fund_categories:
                        fund_categories[category] = {mn: 0 for mn in month_names}
                    fund_categories[category][m_name] += amount
                    
                for m_num in months_list:
                    m_name = f"{m_num}월"
                    chk_y = settings["year"] if m_num >= 3 else settings["year"] + 1
                    folder = f"data/{chk_y}_{m_num:02d}"
                    
                    if not os.path.exists(folder):
                        continue
                        
                    df_enroll = pd.DataFrame(load_data(os.path.join(folder, "enrollments.json"), []))
                    df_prog_fees = pd.DataFrame(load_data(os.path.join(folder, "program_fees.json"), []))
                    df_stud = pd.DataFrame(load_data(os.path.join(folder, "merged_students.json"), []))
                    refunds_data = load_data(os.path.join(folder, "student_refunds.json"), {})
                    df_stats_m = pd.DataFrame(load_data(os.path.join(folder, "instructor_fees.json"), []))
                    
                    subsidy_total = df_stats_m["강사료 보전금"].sum() if not df_stats_m.empty and "강사료 보전금" in df_stats_m.columns else 0
                    if subsidy_total > 0:
                        add_fund("교육청 강사료 보전금 사용액", m_name, subsidy_total)
                        
                    if not df_enroll.empty and not df_prog_fees.empty and not df_stud.empty:
                        df_enroll.columns = df_enroll.columns.astype(str).str.strip()
                        if "프로그램" in df_enroll.columns:
                            melted = df_enroll.rename(columns={"프로그램": "프로그램명"}).copy()
                        elif "프로그램명" in df_enroll.columns:
                            melted = df_enroll.copy()
                        else:
                            id_vars = [c for c in df_enroll.columns if c in ["학년", "반", "번호", "이름"]]
                            melted = df_enroll.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
                            melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
                        
                        melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
                        df_prog_fees["프로그램명"] = df_prog_fees["프로그램명"].astype(str).str.strip()
                        
                        df_calc = pd.merge(melted, df_prog_fees[["프로그램명", "최종 수강료", "월 재료비"]], on="프로그램명", how="inner")
                        
                        merge_keys = [k for k in ["학년", "반", "이름"] if k in df_stud.columns and k in melted.columns]
                        if merge_keys:
                            df_calc = pd.merge(df_calc, df_stud, on=merge_keys, how="left")
                        else:
                            df_calc["가구자격"] = "수익자"
                            
                        df_calc["고유ID"] = df_calc["학년"].astype(str) + "-" + df_calc["반"].astype(str) + "-" + df_calc["이름"] + "_" + df_calc["프로그램명"]
                        
                        for _, r in df_calc.iterrows():
                            fee = r.get("최종 수강료", 0)
                            mat = r.get("월 재료비", 0)
                            qual = str(r.get("가구자격", ""))
                            pri = str(r.get("1순위지원금", ""))
                            dtl = str(r.get("자격상세", "")).strip()
                            
                            if pd.isna(fee): fee = 0
                            if pd.isna(mat): mat = 0
                            if pd.isna(dtl) or dtl in ["", "nan", "None"]: dtl = "미분류"
                            
                            uid = r["고유ID"]
                            ref_amt = refunds_data.get(uid, {}).get("환급액", 0)
                            
                            if qual == "교육비지원":
                                support = fee
                                charge = mat
                            else:
                                support = 0
                                charge = fee + mat
                                
                            final_charge = max(mat, charge - ref_amt)
                            add_fund("학생 수익자 부담액", m_name, final_charge)
                            
                            if support > 0:
                                if pri == "초3이용권":
                                    add_fund("교육비지원 (초3이용권)", m_name, support)
                                elif dtl == "다자녀":
                                    add_fund("교육비지원 (다자녀)", m_name, support)
                                else:
                                    add_fund(f"교육비지원 ({dtl})", m_name, support)
                
                fund_rows = []
                priority_keys = ["학생 수익자 부담액", "교육비지원 (초3이용권)", "교육비지원 (다자녀)"]
                
                sorted_categories = []
                for pk in priority_keys:
                    if pk in fund_categories:
                        sorted_categories.append(pk)
                
                for k in sorted(fund_categories.keys()):
                    if k not in priority_keys and k != "교육청 강사료 보전금 사용액":
                        sorted_categories.append(k)
                        
                if "교육청 강사료 보전금 사용액" in fund_categories:
                    sorted_categories.append("교육청 강사료 보전금 사용액")
                
                for cat in sorted_categories:
                    row_data = {"재원 구분": cat}
                    total = 0
                    for m_name in month_names:
                        val = fund_categories[cat][m_name]
                        row_data[m_name] = val
                        total += val
                    row_data["누계"] = total
                    fund_rows.append(row_data)
                
                if fund_rows:
                    df_fund = pd.DataFrame(fund_rows)
                    
                    st.dataframe(
                        df_fund.style.format({c: "{:,.0f} 원" for c in month_names + ["누계"]}), 
                        use_container_width=True, 
                        hide_index=True
                    )
                    
                    col_f1, col_f2 = st.columns([1, 1])
                    with col_f1:
                        st.download_button("📥 재원별 연간 누적 통계 엑셀 다운로드", data=to_excel(df_fund), file_name="연간_재원별_누적_통계.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stat_fund")
                    with col_f2:
                        st.info("💡 위 통계는 각 재원별(수익자, 지원금, 보전금) 지출 내역을 저장된 모든 월별 데이터를 합산하여 보여줍니다.")
                else:
                    st.info("💡 집계된 월별 정산 데이터가 없습니다.")
            except Exception as e:
                st.error(f"재원별 통계 산출 중 오류가 발생했습니다: {str(e)}")

    else:
        st.info("💡 4번 탭에서 [강사료 정산 및 보전금 내역 저장]을 완료해야 통계 보고서를 볼 수 있습니다.")
"""

with open("app.py", "r", encoding="utf-8") as f:
    code = f.read()

target = '                "강사명": st.column_config.TextColumn(disabled=True),\n'
# Find the LAST occurrence of target
idx = code.rfind(target)

if idx != -1:
    idx += len(target)
    # The file should be truncated here and the missing_block should be appended
    new_code = code[:idx] + missing_block
    with open("app.py", "w", encoding="utf-8") as f:
        f.write(new_code)
    print("Fixed!")
else:
    print("Target not found.")
