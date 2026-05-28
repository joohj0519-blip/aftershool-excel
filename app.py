import streamlit as st
import pandas as pd
from datetime import date, timedelta
import calendar
import json
import os
import io
import zipfile
from st_click_detector import click_detector

st.set_page_config(page_title="방과후학교 자동 정산 시스템", page_icon="🏫", layout="wide")

st.markdown("""
<style>
/* 컨테이너 가로 넓이를 100%로 강제 확장 */
div[data-testid="stAppViewBlockContainer"] {
    max-width: 100% !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}
/* 데이터프레임이 화면 끝까지 채우도록 */
[data-testid="stDataFrame"] {
    width: 100% !important;
}
</style>
""", unsafe_allow_html=True)

SETTINGS_FILE = "settings.json"
HOLIDAYS_FILE = "holidays.json"

def load_data(file_path, default_data):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_data

def save_data(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


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
        merge_keys = [k for k in ["학년", "반", "번호", "이름"] if k in p_stud.columns and k in melted.columns]
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

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

def get_target_grades(df_en):
    if df_en.empty: return {}
    df_temp = df_en.copy()
    df_temp.columns = df_temp.columns.astype(str).str.strip()
    if "프로그램" in df_temp.columns:
        melted = df_temp.rename(columns={"프로그램": "프로그램명"})
    elif "프로그램명" in df_temp.columns:
        melted = df_temp
    else:
        id_vars = [c for c in df_temp.columns if c in ["학년", "반", "번호", "이름"]]
        melted = df_temp.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
        melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
    if "학년" in melted.columns and "프로그램명" in melted.columns:
        melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
        return melted.groupby("프로그램명")["학년"].apply(lambda x: ", ".join(sorted([str(int(g)) for g in set(x.dropna())]))).to_dict()
    return {}

default_settings = {
    "school_name": "○○초등학교", "year": 2026, "region": "제주시 동지역",
    "ext_instructor_fee": 40000, "int_instructor_fee": 33000,
    "tuition_10": 3300, "tuition_15": 2200, "tuition_20": 1650,
    "min_students": 7,
    "support_policies": [
        {"자격명": "초3이용권", "한도액": 500000},
        {"자격명": "자유수강권", "한도액": 600000}
    ]
}

raw_settings = load_data(SETTINGS_FILE, default_settings)
if "support_policies" not in raw_settings:
    raw_settings["support_policies"] = [
        {"자격명": raw_settings.get("priority1_name", "초3이용권"), "한도액": raw_settings.get("priority1_limit", 500000)},
        {"자격명": raw_settings.get("priority2_name", "자유수강권"), "한도액": raw_settings.get("priority2_limit", 600000)}
    ]
settings = raw_settings

st.sidebar.header("🗓️ 작업 월 선택")
month_options = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]
if "selected_month" not in st.session_state:
    st.session_state.selected_month = 3

selected_month = st.sidebar.selectbox(
    "정산할 월을 선택하세요", 
    month_options, 
    index=month_options.index(st.session_state.selected_month),
    format_func=lambda x: f"{x}월"
)

if selected_month != st.session_state.selected_month:
    st.session_state.selected_month = selected_month
    st.rerun()

def get_monthly_path(filename):
    current_year = settings["year"]
    if st.session_state.selected_month < 3:
        current_year += 1
    folder = f"data/{current_year}_{st.session_state.selected_month:02d}"
    if not os.path.exists(folder):
        os.makedirs(folder)
    return os.path.join(folder, filename)

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 전입/전출 관리")

with st.sidebar.expander("➕ 전입생 추가", expanded=False):
    with st.form("transfer_in_form"):
        ti_grade = st.number_input("학년", min_value=1, max_value=6, value=1)
        ti_class = st.text_input("반", value="1")
        ti_num = st.text_input("번호", value="")
        ti_name = st.text_input("이름", value="")
        ti_qual = st.selectbox("가구자격", ["수익자", "교육비지원"])
        
        progs_for_ti = []
        if os.path.exists(get_monthly_path("programs.json")):
            progs_for_ti = pd.DataFrame(load_data(get_monthly_path("programs.json"), []))["프로그램명"].dropna().unique().tolist()
            
        ti_progs = st.multiselect("수강 프로그램 선택", progs_for_ti)
        
        if st.form_submit_button("전입생 등록"):
            if ti_name and ti_progs:
                studs = load_data(get_monthly_path("merged_students.json"), [])
                new_stud = {
                    "학년": ti_grade, "반": ti_class, "번호": ti_num, "이름": ti_name,
                    "자격상세": ti_qual, "가구자격": ti_qual,
                    "추가지원": "초3이용권" if ti_grade == 3 else "",
                    "1순위지원금": "교육비대상자" if ti_qual == "교육비지원" else "수익자",
                    "상태": "재학"
                }
                studs.append(new_stud)
                save_data(get_monthly_path("merged_students.json"), studs)
                
                enrols = load_data(get_monthly_path("enrollments.json"), [])
                for p in ti_progs:
                    enrols.append({
                        "학년": ti_grade, "반": ti_class, "번호": ti_num, "이름": ti_name,
                        "프로그램명": p, "신청여부": "O"
                    })
                save_data(get_monthly_path("enrollments.json"), enrols)
                st.success(f"{ti_name} 전입생 등록 완료!")
                st.rerun()
            else:
                st.warning("이름과 수강 프로그램을 입력해주세요.")

with st.sidebar.expander("➖ 전출생/취소 처리", expanded=False):
    studs = load_data(get_monthly_path("merged_students.json"), [])
    if studs:
        df_stud_side = pd.DataFrame(studs)
        if "상태" not in df_stud_side.columns:
            df_stud_side["상태"] = "재학"
            
        active_studs = df_stud_side[~df_stud_side["상태"].isin(["전출", "수강취소"])]
        if not active_studs.empty:
            stud_list = (active_studs["학년"].astype(str) + "-" + active_studs["반"].astype(str) + "-" + active_studs["이름"]).tolist()
            sel_to_out = st.selectbox("전출/취소 처리할 학생 선택", stud_list)
            
            action_type = st.radio("처리 구분", ["전출", "수강취소"], horizontal=True)
            
            if st.button("선택 학생 처리"):
                parts = sel_to_out.split("-")
                gr, cl, nm = parts[0], parts[1], parts[2]
                
                for s in studs:
                    if str(s.get("학년")) == gr and str(s.get("반")) == cl and str(s.get("이름")) == nm:
                        s["상태"] = action_type
                save_data(get_monthly_path("merged_students.json"), studs)
                st.success(f"{nm} 학생 {action_type} 처리 완료. (정산표에는 유지되므로 환급액을 입력하세요)")
                st.rerun()
        else:
            st.caption("재학 중인 학생이 없습니다.")
    else:
        st.caption("먼저 학생 명단을 업로드해주세요.")

st.sidebar.markdown("---")
st.sidebar.subheader("📦 자료 다운로드")
if os.path.exists(get_monthly_path("merged_students.json")):
    def generate_zip(m):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            studs = load_data(get_monthly_path("merged_students.json"), [])
            if studs:
                zip_file.writestr(f"1_통합학생명단_{m}월.xlsx", to_excel(pd.DataFrame(studs)))
                
            insts = load_data(get_monthly_path("instructor_fees.json"), [])
            if insts:
                df_inst = pd.DataFrame(insts)
                zip_file.writestr(f"3_강사료_정산표_{m}월.xlsx", to_excel(df_inst))
                report_cols = ["프로그램명", "강사명", "강사구분", "총 수강료 수입", "교육비지원대상 총액", "수익자 부담액", "총 강사료(예상)", "강사료 보전금"]
                df_report = df_inst[[c for c in report_cols if c in df_inst.columns]]
                zip_file.writestr(f"4_월간_통계보고서_{m}월.xlsx", to_excel(df_report))
                
            enrolls = load_data(get_monthly_path("enrollments.json"), [])
            prog_fees = load_data(get_monthly_path("program_fees.json"), [])
            refunds = load_data(get_monthly_path("student_refunds.json"), {})
            retro = load_data(get_monthly_path("retroactive_adjustments.json"), {})
            
            if enrolls and studs and prog_fees:
                df_en = pd.DataFrame(enrolls)
                df_st = pd.DataFrame(studs)
                df_pf = pd.DataFrame(prog_fees)
                
                if "프로그램명" in df_en.columns:
                    melted = df_en.copy()
                elif "프로그램" in df_en.columns:
                    melted = df_en.rename(columns={"프로그램": "프로그램명"})
                else:
                    id_vars = [c for c in df_en.columns if c in ["학년", "반", "번호", "이름"]]
                    melted = df_en.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
                    melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
                    
                if not melted.empty:
                    melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
                    df_pf["프로그램명"] = df_pf["프로그램명"].astype(str).str.strip()
                    
                    merge_keys = [k for k in ["학년", "반", "번호", "이름"] if k in df_st.columns and k in melted.columns]
                    if merge_keys:
                        df_calc = pd.merge(melted, df_st, on=merge_keys, how="left")
                    else:
                        df_calc = melted.copy()
                        df_calc["가구자격"] = "수익자"
                        
                    if "최종 수강료" in df_pf.columns:
                        df_calc = pd.merge(df_calc, df_pf[["프로그램명", "최종 수강료", "월 재료비"]], on="프로그램명", how="inner")
                        df_calc["고유ID"] = df_calc["학년"].astype(str) + "-" + df_calc["반"].astype(str) + "-" + df_calc["이름"] + "_" + df_calc["프로그램명"]
                        
                        def calc_fees_export(row):
                            fee = row.get("최종 수강료", 0)
                            mat = row.get("월 재료비", 0)
                            if pd.isna(fee): fee = 0
                            if pd.isna(mat): mat = 0
                            qual = str(row.get("가구자격", ""))
                            total = fee + mat
                            if qual == "교육비지원":
                                support, charge, mat_charge = total, 0, 0
                            else:
                                support, charge, mat_charge = 0, total, mat
                            uid = row["고유ID"]
                            r_info = refunds.get(uid, {})
                            refund_amt = r_info.get("환급액", 0)
                            retro_info = retro.get(uid, {})
                            r_add = retro_info.get("추가징수액", 0)
                            r_sub = retro_info.get("소급환급액", 0)
                            base_final = max(mat_charge, charge - refund_amt)
                            final_charge = base_final + r_add - r_sub
                            return pd.Series([total, support, charge, r_add, r_sub, refund_amt, r_info.get("환급사유", ""), final_charge])
                            
                        df_calc[["총 금액", "지원금(면제)", "기본 징수액", "추가징수액", "소급환급액", "환급액", "환급사유", "최종 징수액"]] = df_calc.apply(calc_fees_export, axis=1)
                        display_cols = ["학년", "반", "이름", "프로그램명", "가구자격", "총 금액", "지원금(면제)", "기본 징수액", "추가징수액", "소급환급액", "환급액", "환급사유", "최종 징수액"]
                        df_display = df_calc[[c for c in display_cols if c in df_calc.columns]].sort_values(by=["프로그램명", "학년", "반", "이름"])
                        zip_file.writestr(f"2_수강료_정산표_{m}월.xlsx", to_excel(df_display))
        return zip_buffer.getvalue()

    st.sidebar.download_button(
        "📦 이번 달 정산자료 일괄 다운로드(ZIP)", 
        data=generate_zip(st.session_state.selected_month), 
        file_name=f"{st.session_state.selected_month}월_정산자료_통합.zip", 
        mime="application/zip",
        use_container_width=True
    )

# 마이그레이션 (기존 루트 파일 이동)
if not os.path.exists("data"):
    os.makedirs(f"data/{settings['year']}_03", exist_ok=True)
    import shutil
    for fname in ["merged_students.json", "programs.json", "enrollments.json", "program_fees.json", "instructor_fees.json", "student_refunds.json"]:
        if os.path.exists(fname):
            try:
                shutil.move(fname, f"data/{settings['year']}_03/{fname}")
            except:
                pass

default_holidays = {
    "2026-03-02": "삼일절 대체휴일", "2026-05-01": "근로자의 날", "2026-05-04": "재량휴업일", 
    "2026-05-05": "어린이날", "2026-05-25": "부처님오신날 대체", "2026-06-03": "지방선거일", 
    "2026-07-17": "제헌절", "2026-08-17": "광복절 대체", "2026-09-24": "추석 연휴", 
    "2026-09-25": "추석", "2026-10-05": "개천절 대체", "2026-10-09": "한글날", 
    "2026-12-25": "성탄절", "2027-01-01": "신정", "2027-01-09": "졸업식"
}
holidays = load_data(HOLIDAYS_FILE, default_holidays)

if "clicked_date" not in st.session_state:
    st.session_state.clicked_date = ""

class CustomHTMLCalendar(calendar.HTMLCalendar):
    def __init__(self, holidays_dict, year, month):
        super().__init__()
        self.holidays_dict = holidays_dict
        self.year = year
        self.month = month

    def formatweekheader(self):
        kor_days = ["월", "화", "수", "목", "금", "토", "일"]
        s = ''.join(f'<th class="{self.cssclasses[i]}">{day}</th>' for i, day in enumerate(kor_days))
        return f'<tr>{s}</tr>'

    def formatday(self, day, weekday):
        if day == 0:
            return '<td class="noday">&nbsp;</td>'
        current_date = f"{self.year}-{self.month:02d}-{day:02d}"
        css_class = 'day'
        if current_date in self.holidays_dict:
            if "방과후" in self.holidays_dict[current_date]:
                css_class += ' no-afterschool'
            else:
                css_class += ' holiday'
        elif weekday == 5:
            css_class += ' saturday'
        elif weekday == 6:
            css_class += ' sunday'
        title = ""
        if current_date in self.holidays_dict:
            title = f' title="{self.holidays_dict[current_date]}"'
        return f'<td class="{css_class}"{title}><a href="#" id="{current_date}" class="day-link">{day}</a></td>'

    def formatmonth(self, withyear=True):
        v = []
        a = v.append
        a(f'<table border="0" cellpadding="0" cellspacing="0" class="month">')
        a('\n')
        if withyear:
            a(self.formatmonthname(self.year, self.month, withyear=True))
        a('\n')
        a(self.formatweekheader())
        a('\n')
        for week in self.monthdays2calendar(self.year, self.month):
            a(self.formatweek(week))
            a('\n')
        a('</table>')
        a('\n')
        return ''.join(v)

st.title("🏫 방과후학교 전용 대시보드")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📅 1. 학사일정 및 설정", 
    "👩‍🎓 2. 기초자료 (학생/프로그램)", 
    "💰 3. 수강료 정산", 
    "👨‍🏫 4. 강사료 정산", 
    "📈 5. 통계",
    "📊 6. 통합 대시보드"
])

with tab1:
    st.header("⚙️ 1. 연간 기본 셋팅")
    
    with st.expander("📌 연간 기본 설정 값 열기/수정하기 (클릭)", expanded=False):
        with st.form("unified_settings_form"):
            scol1, scol2, scol3 = st.columns(3)
            
            with scol1:
                st.subheader("📌 기본 정보")
                new_school = st.text_input("학교명", value=settings["school_name"])
                new_year = st.number_input("학년도", value=settings["year"], step=1)
                new_region = st.selectbox("지역 선택", ["제주시 동지역", "제주시 읍면지역", "서귀포시 동지역", "서귀포시 읍면지역"], 
                                          index=0 if settings["region"] not in ["제주시 동지역", "제주시 읍면지역", "서귀포시 동지역", "서귀포시 읍면지역"] else ["제주시 동지역", "제주시 읍면지역", "서귀포시 동지역", "서귀포시 읍면지역"].index(settings["region"]))

            with scol2:
                st.subheader("💰 단가 및 개설 기준")
                new_ext_fee = st.number_input("외부강사 단가(차시당)", value=settings.get("ext_instructor_fee", 40000), step=1000)
                new_int_fee = st.number_input("내부강사 단가(차시당)", value=settings.get("int_instructor_fee", 33000), step=1000)
                new_min_st = st.number_input("최소 개설 인원", value=settings.get("min_students", 7), step=1)
                st.markdown("---")
                st.caption("기본 수강료 단가 (수강정원별)")
                new_t10 = st.number_input("10명 이하 (원)", value=settings.get("tuition_10", 3300), step=100)
                new_t15 = st.number_input("11~15명 (원)", value=settings.get("tuition_15", 2200), step=100)
                new_t20 = st.number_input("16명 이상 (원)", value=settings.get("tuition_20", 1650), step=100)

            with scol3:
                st.subheader("🎓 지원자격 및 우선순위")
                st.caption("💡 지우고 싶은 항목은 글자를 전부 지우거나, 행 맨 앞 번호를 누르고 Delete키를 누르세요.")
                df_policies = pd.DataFrame(settings["support_policies"])
                
                edited_df = st.data_editor(
                    df_policies,
                    num_rows="dynamic",
                    column_config={
                        "자격명": st.column_config.TextColumn("자격명 (예: 자유수강권)"),
                        "한도액": st.column_config.NumberColumn("연간 한도액(원)", min_value=0, step=10000, format="%d")
                    },
                    hide_index=False,
                    key="policy_editor"
                )
            
            st.markdown("---")
            submitted = st.form_submit_button("✅ 위 설정 내용 한 번에 모두 저장하기", use_container_width=True)
            if submitted:
                clean_df = edited_df.replace("", pd.NA).dropna(subset=["자격명", "한도액"])
                new_policies = clean_df.to_dict("records")
                
                settings.update({
                    "school_name": new_school, "year": new_year, "region": new_region,
                    "ext_instructor_fee": new_ext_fee, "int_instructor_fee": new_int_fee,
                    "min_students": new_min_st,
                    "tuition_10": new_t10, "tuition_15": new_t15, "tuition_20": new_t20,
                    "support_policies": new_policies
                })
                save_data(SETTINGS_FILE, settings)
                st.success("모든 연간 셋팅이 한 번에 성공적으로 저장되었습니다!")
                st.rerun()

    st.markdown("---")
    st.header("📅 2. 학사일정 및 휴업일 관리")
    st.info("💡 아래 달력에서 날짜를 **직접 클릭**하여 우측 창에서 휴업일 또는 방과후 미운영일을 추가하거나 삭제하세요!")
    
    c_col1, c_col2 = st.columns([1.6, 1.2])

    start_date = date(settings["year"], 3, 1)
    end_date = date(settings["year"] + 1, 2, 28)
    months = []
    current_date = start_date
    while current_date <= end_date:
        if current_date.day == 1:
            months.append((current_date.year, current_date.month))
        current_date += timedelta(days=1)
    if (start_date.year, start_date.month) not in months:
        months.insert(0, (start_date.year, start_date.month))

    with c_col1:
        # 달력 전용 CSS를 반드시 이 위치에 두어 iframe 내부로 주입해야 합니다!!
        calendar_css = """
        <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; }
        a { text-decoration: none; }
        
        body { color: #e2e8f0; }
        .month th { background-color: #334155; color: #e2e8f0; }
        .month td { border: 1px solid #475569; }
        .day-link { color: #e2e8f0; }
        .saturday a { color: #93c5fd !important; }
        .sunday a { color: #fca5a5 !important; }
        .holiday { background-color: #991b1b; }
        .holiday a { color: #fee2e2 !important; }
        .no-afterschool { background-color: #a16207; }
        .no-afterschool a { color: #fef08a !important; }

        @media (prefers-color-scheme: light) {
            body { color: #1e293b; }
            .month th { background-color: #f1f5f9; color: #1e293b; }
            .month td { border: 1px solid #cbd5e1; }
            .day-link { color: #1e293b; }
            .saturday a { color: #2563eb !important; }
            .sunday a { color: #dc2626 !important; }
            .holiday { background-color: #fecaca; }
            .holiday a { color: #991b1b !important; }
            .no-afterschool { background-color: #fef08a; }
            .no-afterschool a { color: #854d0e !important; }
        }

        .cal-row { display: flex; flex-wrap: nowrap; justify-content: flex-start; gap: 40px; margin-bottom: 30px;}
        .cal-col { flex: 1; min-width: 250px; }
        .month { width: 100%; border-collapse: collapse; text-align: center; }
        .month th { padding: 6px; font-weight: bold; font-size: 0.9em; }
        .month td { padding: 8px; font-size: 0.9em; }
        .day-link { display: block; width: 100%; height: 100%; }
        .day-link:hover { background-color: #3b82f6; color: white !important; border-radius: 4px; }
        .holiday, .no-afterschool { border-radius: 4px; font-weight: bold; }
        .noday { border: none !important; }
        .month-title { text-align: center; font-weight: bold; font-size: 1.1em; margin-bottom: 12px; }
        </style>
        """

        html_content = calendar_css + "<div class='calendar-container'>"
        for row in range(4):
            html_content += "<div class='cal-row'>"
            for col_idx in range(3):
                month_idx = row * 3 + col_idx
                if month_idx < len(months):
                    y, m = months[month_idx]
                    cal = CustomHTMLCalendar(holidays, y, m)
                    html_content += f"<div class='cal-col'><div class='month-title'>{y}년 {m}월</div>"
                    html_content += cal.formatmonth(withyear=False)
                    html_content += "</div>"
            html_content += "</div>"
        html_content += "</div>"

        clicked = click_detector(html_content)
        if clicked and clicked != st.session_state.clicked_date:
            st.session_state.clicked_date = clicked
            st.rerun()

    with c_col2:
        st.subheader("📝 휴업일 등록/수정 창")
        if st.session_state.clicked_date:
            st.warning(f"👉 **{st.session_state.clicked_date} 설정 중**")
            
            is_existing = st.session_state.clicked_date in holidays
            current_name = holidays.get(st.session_state.clicked_date, "")
            
            h_type = "휴업일 (공휴일, 개교기념일 등)"
            if "방과후" in current_name:
                h_type = "방과후 미운영일 (방학 등)"
                current_name = current_name.replace("[방과후 미운영일] ", "")
            
            with st.form("holiday_form"):
                sel_type = st.radio("일정 종류 선택", ["휴업일 (공휴일, 재량휴업일 등)", "방과후 미운영일 (방학 등)"], index=1 if "방과후" in h_type else 0)
                name_input = st.text_input("일정 이름 (예: 개교기념일)", value=current_name)
                
                f_col1, f_col2 = st.columns(2)
                with f_col1:
                    if st.form_submit_button("저장/수정", use_container_width=True):
                        prefix = "[방과후 미운영일] " if "미운영일" in sel_type else ""
                        holidays[st.session_state.clicked_date] = prefix + name_input
                        save_data(HOLIDAYS_FILE, holidays)
                        st.session_state.clicked_date = ""
                        st.rerun()
                with f_col2:
                    if is_existing:
                        if st.form_submit_button("삭제", use_container_width=True):
                            del holidays[st.session_state.clicked_date]
                            save_data(HOLIDAYS_FILE, holidays)
                            st.session_state.clicked_date = ""
                            st.rerun()
        else:
            st.info("👈 달력에서 원하는 날짜를 클릭하시면 이 곳에 창이 활성화됩니다.")
            with st.form("holiday_form_disabled"):
                st.radio("일정 종류 선택", ["휴업일 (공휴일, 재량휴업일 등)", "방과후 미운영일 (방학 등)"], disabled=True)
                st.text_input("일정 이름 (예: 개교기념일)", disabled=True)
                st.form_submit_button("저장/수정", disabled=True)
        
        st.markdown("---")
        
        st.subheader("📈 요일별 시수 및 내역")
        
        summary_data = []
        for y, m in months:
            num_days = calendar.monthrange(y, m)[1]
            days_count = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
            month_holidays = []
            
            for d in range(1, num_days + 1):
                chk_date = date(y, m, d)
                weekday = chk_date.weekday()
                chk_str = chk_date.strftime("%Y-%m-%d")
                
                if chk_str in holidays:
                    kor_wd = ["월","화","수","목","금","토","일"][weekday]
                    holiday_name = holidays[chk_str].replace("[방과후 미운영일] ", "[미운영] ")
                    month_holidays.append(f"{d}일({kor_wd}) {holiday_name}")
                    continue
                if weekday < 5:
                    days_count[weekday] += 1
                    
            summary_data.append({
                "해당월": f"{m}월",
                "월": days_count[0], "화": days_count[1], "수": days_count[2],
                "목": days_count[3], "금": days_count[4],
                "계": sum(days_count.values()),
                "내역": ", ".join(month_holidays) if month_holidays else "-"
            })
            
        summary_df = pd.DataFrame(summary_data)
        
        sums = summary_df[["월", "화", "수", "목", "금", "계"]].sum(numeric_only=True)
        sum_row = pd.DataFrame({
            "해당월": ["합계"], 
            "월": [sums["월"]], "화": [sums["화"]], "수": [sums["수"]], 
            "목": [sums["목"]], "금": [sums["금"]], "계": [sums["계"]],
            "내역": [""]
        })
        summary_df = pd.concat([summary_df, sum_row], ignore_index=True)
        
        def highlight_sum(s):
            if s["해당월"] == "합계":
                return ['background-color: #1e3a8a; color: white; font-weight: bold'] * len(s)
            return [''] * len(s)

        st.dataframe(summary_df.style.apply(highlight_sum, axis=1), use_container_width=True, hide_index=True)

with tab2:
    st.header("📥 기초자료 파일 업로드")
    st.markdown("매월 작업하실 **방과후 기초자료 엑셀 파일**을 이곳에 업로드해주세요.")
    
    uploaded_file = st.file_uploader("엑셀 파일 선택", type=["xlsx", "xls"])
    
    if uploaded_file is not None:
        try:
            xls = pd.ExcelFile(uploaded_file)
            sheet_names = xls.sheet_names
            
            req_sheets = ["학생지원자격", "전체프로그램"]
            missing_sheets = [s for s in req_sheets if s not in sheet_names]
            
            if missing_sheets:
                st.error(f"❌ 엑셀 파일에 다음 필수 시트가 없습니다: {', '.join(missing_sheets)}")
            else:
                app_sheets = [s for s in sheet_names if "신청명단" in s]
                
                if not app_sheets:
                    st.warning("⚠️ '신청명단'이라는 단어가 포함된 시트를 찾을 수 없습니다. 사용할 시트를 수동으로 선택해주세요.")
                    selected_app_sheet = st.selectbox("수강신청 명단 시트 선택", sheet_names)
                else:
                    selected_app_sheet = st.selectbox("수강신청 명단 시트 선택", app_sheets, index=0)
                
                carry_over_refunds = False
                months_seq = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]
                try:
                    curr_idx = months_seq.index(st.session_state.selected_month)
                    if curr_idx > 0:
                        prev_m = months_seq[curr_idx - 1]
                        prev_y = settings["year"] if prev_m >= 3 else settings["year"] + 1
                        prev_folder = f"data/{prev_y}_{prev_m:02d}"
                        if os.path.exists(os.path.join(prev_folder, "student_refunds.json")):
                            carry_over_refunds = st.checkbox(f"🔄 이전 달({prev_m}월)의 환급 내역을 당월로 자동 이월(복사)하기", value=True)
                except ValueError:
                    pass
                
                if st.button("데이터 분석 및 저장", use_container_width=True, type="primary"):
                    with st.spinner("데이터를 분석하고 있습니다..."):
                        # Read data
                        df_all_students = pd.read_excel(uploaded_file, sheet_name="전체학생명단", skiprows=1).dropna(how='all').fillna("")
                        df_students = pd.read_excel(uploaded_file, sheet_name="학생지원자격", skiprows=1).dropna(how='all').fillna("")
                        df_programs = pd.read_excel(uploaded_file, sheet_name="전체프로그램", skiprows=1).dropna(how='all').fillna("")
                        df_enrollments = pd.read_excel(uploaded_file, sheet_name=selected_app_sheet, skiprows=1).dropna(how='all').fillna("")
                        
                        # --- 데이터 병합 및 변환 로직 ---
                        merge_cols = ["학년", "반", "번호", "이름"]
                        df_merged = pd.merge(df_all_students, df_students, on=merge_cols, how="left")
                        
                        df_merged["자격상세"] = df_merged["가구자격"].fillna("수익자").replace("", "수익자")
                        df_merged["추가지원"] = df_merged["추가지원"].fillna("")
                        
                        voucher_keywords = ["생계급여", "의료급여", "주거급여", "교육급여", "한부모", "차상위", "학교장추천", "국가유공자", "다자녀", "탈북", "다문화", "조손가정", "소년소녀", "보훈대상자", "특수교육대상", "난민", "기타대상자"]
                        def map_qualification(q):
                            q_str = str(q)
                            if any(kw in q_str for kw in voucher_keywords):
                                return "교육비지원"
                            return "수익자" if q_str.strip() == "" else q_str
                            
                        df_merged["가구자격"] = df_merged["자격상세"].apply(map_qualification)
                        df_merged.loc[df_merged["학년"] == 3, "추가지원"] = "초3이용권"
                        
                        def assign_priority(row):
                            grade = row["학년"]
                            qual = row["가구자격"]
                            if grade == 3:
                                return pd.Series(["초3이용권", "교육비대상자" if qual == "교육비지원" else "수익자", ""])
                            else:
                                return pd.Series(["교육비대상자" if qual == "교육비지원" else "수익자", "", ""])
                                
                        df_merged[["1순위지원금", "2순위지원금", "3순위지원금"]] = df_merged.apply(assign_priority, axis=1)
                        df_merged["상태"] = "재학"
                        df_merged = df_merged.sort_values(by=["학년", "반", "번호"])
                        
                        final_student_cols = ["학년", "반", "번호", "이름", "자격상세", "가구자격", "추가지원", "1순위지원금", "2순위지원금", "3순위지원금", "상태"]
                        df_merged = df_merged[final_student_cols]
                        
                        # 프로그램 목록 컬럼 필터링
                        prog_cols = [c for c in ["강사명", "프로그램명", "운영요일", "운영시간", "수강정원", "정원", "수강인원", "대기인원", "대기자인원", "강사구분", "차시당단가", "재료비", "월재료비", "월 재료비", "최종 수강료"] if c in df_programs.columns]
                        df_prog_display = df_programs[prog_cols] if prog_cols else df_programs
                        
                        prog_grades = get_target_grades(df_enrollments)
                        df_prog_display["신청 학년"] = df_prog_display["프로그램명"].astype(str).str.strip().map(prog_grades).fillna("-")
                        
                        # Save with Backup
                        import datetime
                        import shutil
                        if os.path.exists(get_monthly_path("merged_students.json")):
                            os.makedirs("archive", exist_ok=True)
                            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            for fname in ["merged_students.json", "programs.json", "enrollments.json"]:
                                if os.path.exists(fname):
                                    shutil.copy(fname, f"archive/{timestamp}_{fname}")
                                    
                        save_data(get_monthly_path("merged_students.json"), df_merged.to_dict(orient="records"))
                        save_data(get_monthly_path("programs.json"), df_programs.to_dict(orient="records"))
                        save_data(get_monthly_path("enrollments.json"), df_enrollments.to_dict(orient="records"))
                        
                        if carry_over_refunds:
                            try:
                                prev_m = months_seq[months_seq.index(st.session_state.selected_month) - 1]
                                prev_y = settings["year"] if prev_m >= 3 else settings["year"] + 1
                                prev_folder = f"data/{prev_y}_{prev_m:02d}"
                                prev_refunds = load_data(os.path.join(prev_folder, "student_refunds.json"), {})
                                if prev_refunds:
                                    save_data(get_monthly_path("student_refunds.json"), prev_refunds)
                            except:
                                pass
                        
                        st.success("✅ 파일이 성공적으로 업로드 및 분석되었습니다!")
                        
                        scol1, scol2, scol3 = st.columns(3)
                        scol1.metric("총 등록 학생 수", f"{len(df_merged)} 명")
                        scol2.metric("개설 프로그램 수", f"{len(df_programs)} 개")
                        scol3.metric("총 수강 건수", f"{len(df_enrollments)} 건")
                        
                        grade_counts = df_merged["학년"].value_counts().sort_index()
                        grade_summary = " · ".join([f"{int(k)}학년 {v}명" for k, v in grade_counts.items() if pd.notnull(k)])
                        st.caption(f"**학년별 학생 수:** {grade_summary}")
                        
                        qual_counts = df_merged["자격상세"].value_counts()
                        qual_summary = " | ".join([f"{k} {v}명" for k, v in qual_counts.items()])
                        st.info(f"**전체 학생:** {len(df_merged)}명\n\n**자격 현황:** {qual_summary}")

                        st.markdown("### 🔍 통합 기초데이터 미리보기")
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            f1, f2, f3 = st.columns(3)
                            with f1:
                                sel_grade = st.multiselect("학년 필터", sorted([str(x) for x in df_merged["학년"].unique()]), key="grade_1")
                            with f2:
                                sel_pri = st.multiselect("지원금 필터", sorted([str(x) for x in df_merged["1순위지원금"].unique()]), key="pri_1")
                            with f3:
                                sel_qual = st.multiselect("자격 필터", sorted([str(x) for x in df_merged["자격상세"].unique()]), key="qual_1")
                            
                            df_disp = df_merged.copy()
                            if sel_grade:
                                df_disp = df_disp[df_disp["학년"].astype(str).isin(sel_grade)]
                            if sel_qual:
                                df_disp = df_disp[df_disp["자격상세"].astype(str).isin(sel_qual)]
                            if sel_pri:
                                df_disp = df_disp[df_disp["1순위지원금"].astype(str).isin(sel_pri)]
                                
                            st.caption(f"👩‍🎓 **통합 학생 명단** (총 {len(df_disp)}명)")
                            st.download_button("📥 학생 명단 엑셀 다운로드", data=to_excel(df_disp), file_name="학생명단.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stud_1")
                            st.dataframe(df_disp, height=1050, use_container_width=True, hide_index=True)
                            
                        with c2:
                            cap_container = st.container()
                            p1, p2, p3 = st.columns(3)
                            with p1:
                                all_grades = set()
                                if "신청 학년" in df_prog_display.columns:
                                    for g in df_prog_display["신청 학년"].dropna():
                                        all_grades.update([x.strip() for x in str(g).split(",") if x.strip() != "-"])
                                sel_grade_prog = st.multiselect("신청 학년 필터", sorted(list(all_grades)), key="grade_prog_1")
                            with p2:
                                all_days = set()
                                for d in df_programs["운영요일"].dropna():
                                    all_days.update([x.strip() for x in str(d).split(",")])
                                sel_day = st.multiselect("운영요일 필터", sorted(list(all_days)), key="day_1")
                                
                            df_prog_disp = df_prog_display.copy()
                            if sel_day:
                                df_prog_disp = df_prog_disp[df_prog_disp["운영요일"].apply(lambda x: any(d in str(x) for d in sel_day))]
                            if sel_grade_prog and "신청 학년" in df_prog_disp.columns:
                                df_prog_disp = df_prog_disp[df_prog_disp["신청 학년"].apply(lambda x: any(g in str(x) for g in sel_grade_prog))]
                                
                            internal_count = len(df_programs[df_programs["강사구분"] == "내부"])
                            external_count = len(df_programs[df_programs["강사구분"] == "외부"])
                            cap_container.caption(f"📚 **개설 프로그램 목록** (총 {len(df_prog_disp)}개) | 👨‍🏫 내부강사 {internal_count}명 / 외부강사 {external_count}명")
                            
                            st.markdown("<div style='height: 52px;'></div>", unsafe_allow_html=True)
                            
                            format_dict = {c: "{:,.0f} 원" for c in ["최종 수강료", "월 재료비", "차시당단가", "재료비", "월재료비"] if c in df_prog_disp.columns}
                            st.dataframe(df_prog_disp.style.format(format_dict), height=1050, use_container_width=True, hide_index=True)
                            
                        st.info("기초 데이터가 완벽하게 통합되었습니다! 이제 [📊 정산 결과 다운로드] 탭에서 결과를 확인하세요.")
                        
        except Exception as e:
            st.error(f"엑셀 파일을 읽는 중 오류가 발생했습니다: {str(e)}")
            
    elif os.path.exists(get_monthly_path("merged_students.json")) and os.path.exists(get_monthly_path("programs.json")) and os.path.exists(get_monthly_path("enrollments.json")):
        st.success("✅ 이전에 업로드된 데이터가 저장되어 있습니다.")
        df_merged = pd.DataFrame(load_data(get_monthly_path("merged_students.json"), []))
        df_programs = pd.DataFrame(load_data(get_monthly_path("programs.json"), []))
        df_enrollments = pd.DataFrame(load_data(get_monthly_path("enrollments.json"), []))
        
        prog_cols = [c for c in ["강사명", "프로그램명", "운영요일", "운영시간", "수강정원", "정원", "수강인원", "대기인원", "대기자인원", "강사구분", "차시당단가", "재료비", "월재료비", "월 재료비", "최종 수강료"] if c in df_programs.columns]
        df_prog_display = df_programs[prog_cols] if prog_cols else df_programs
        
        prog_grades = get_target_grades(df_enrollments)
        df_prog_display["신청 학년"] = df_prog_display["프로그램명"].astype(str).str.strip().map(prog_grades).fillna("-")
        
        scol1, scol2, scol3 = st.columns(3)
        scol1.metric("저장된 통합 학생 수", f"{len(df_merged)} 명")
        scol2.metric("저장된 프로그램 수", f"{len(df_programs)} 개")
        scol3.metric("저장된 수강 건수", f"{len(df_enrollments)} 건")
        
        if "학년" in df_merged.columns:
            grade_counts = df_merged["학년"].value_counts().sort_index()
            grade_summary = " · ".join([f"{int(k)}학년 {v}명" for k, v in grade_counts.items() if pd.notnull(k)])
            st.caption(f"**학년별 학생 수:** {grade_summary}")
        
        if "자격상세" in df_merged.columns:
            qual_counts = df_merged["자격상세"].value_counts()
            qual_summary = " | ".join([f"{k} {v}명" for k, v in qual_counts.items()])
            st.info(f"**전체 학생:** {len(df_merged)}명\n\n**자격 현황:** {qual_summary}")

        st.markdown("### 🔍 통합 기초데이터 미리보기")
        
        c1, c2 = st.columns(2)
        with c1:
            f1, f2, f3 = st.columns(3)
            with f1:
                sel_grade = st.multiselect("학년 필터", sorted([str(x) for x in df_merged["학년"].unique()]), key="grade_2")
            with f2:
                sel_pri = st.multiselect("지원금 필터", sorted([str(x) for x in df_merged["1순위지원금"].unique()]), key="pri_2")
            with f3:
                sel_qual = st.multiselect("자격 필터", sorted([str(x) for x in df_merged["자격상세"].unique()]), key="qual_2")
            
            df_disp = df_merged.copy()
            if sel_grade:
                df_disp = df_disp[df_disp["학년"].astype(str).isin(sel_grade)]
            if sel_qual:
                df_disp = df_disp[df_disp["자격상세"].astype(str).isin(sel_qual)]
            if sel_pri:
                df_disp = df_disp[df_disp["1순위지원금"].astype(str).isin(sel_pri)]

            st.caption(f"👩‍🎓 **통합 학생 명단** (총 {len(df_disp)}명)")
            st.download_button("📥 학생 명단 엑셀 다운로드", data=to_excel(df_disp), file_name="학생명단.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stud_2")
            st.dataframe(df_disp, height=1050, use_container_width=True, hide_index=True)

        with c2:
            cap_container = st.container()
            p1, p2, p3 = st.columns(3)
            with p1:
                all_grades = set()
                if "신청 학년" in df_prog_display.columns:
                    for g in df_prog_display["신청 학년"].dropna():
                        all_grades.update([x.strip() for x in str(g).split(",") if x.strip() != "-"])
                sel_grade_prog = st.multiselect("신청 학년 필터", sorted(list(all_grades)), key="grade_prog_2")
            with p2:
                all_days = set()
                for d in df_programs["운영요일"].dropna():
                    all_days.update([x.strip() for x in str(d).split(",")])
                sel_day = st.multiselect("운영요일 필터", sorted(list(all_days)), key="day_2")
                
            df_prog_disp = df_prog_display.copy()
            if sel_day:
                df_prog_disp = df_prog_disp[df_prog_disp["운영요일"].apply(lambda x: any(d in str(x) for d in sel_day))]
            if sel_grade_prog and "신청 학년" in df_prog_disp.columns:
                df_prog_disp = df_prog_disp[df_prog_disp["신청 학년"].apply(lambda x: any(g in str(x) for g in sel_grade_prog))]
                
            internal_count = len(df_programs[df_programs["강사구분"] == "내부"])
            external_count = len(df_programs[df_programs["강사구분"] == "외부"])
            cap_container.caption(f"📚 **개설 프로그램 목록** (총 {len(df_prog_disp)}개) | 👨‍🏫 내부강사 {internal_count}명 / 외부강사 {external_count}명")
            
            st.markdown("<div style='height: 52px;'></div>", unsafe_allow_html=True)
            
            format_dict = {c: "{:,.0f} 원" for c in ["최종 수강료", "월 재료비", "차시당단가", "재료비", "월재료비"] if c in df_prog_disp.columns}
            st.dataframe(df_prog_disp.style.format(format_dict), height=1050, use_container_width=True, hide_index=True)
            
        st.info("새로운 달의 정산을 하려면 위에 새 파일을 업로드해주세요.")
        
    st.markdown("---")
    st.subheader("🔄 학년초 진급(학적 변동) 자동 매칭")
    st.info("💡 12월 수강신청 명단(과거 학적)을 3월 새 학적으로 원클릭 업데이트하려면 나이스(NEIS) 진급 명단을 업로드하세요.")
    
    neis_file = st.file_uploader("나이스 진급 명단 엑셀 업로드", type=["xlsx", "xls"], key="neis_upload")
    if neis_file is not None:
        if st.button("진급 학적 자동 업데이트 실행", type="primary"):
            if not os.path.exists(get_monthly_path("merged_students.json")):
                st.error("먼저 위의 '기초자료 파일'을 업로드하여 명단을 저장해주세요.")
            else:
                try:
                    df_neis = pd.read_excel(neis_file)
                    old_new_map = {}
                    for i, row in df_neis.iterrows():
                        try:
                            n_gr = str(row.iloc[0]).replace("학년", "").strip()
                            n_cl = str(row.iloc[1]).strip()
                            n_num = str(row.iloc[2]).strip()
                            name = str(row.iloc[3]).strip()
                            
                            o_gr = str(row.iloc[4]).replace("학년", "").strip()
                            o_cl = str(row.iloc[5]).strip()
                            o_num = str(row.iloc[6]).strip()
                            
                            if name and o_gr and o_cl:
                                old_new_map[(o_gr, o_cl, name)] = (n_gr, n_cl, n_num)
                        except:
                            continue
                            
                    studs = load_data(get_monthly_path("merged_students.json"), [])
                    enrols = load_data(get_monthly_path("enrollments.json"), [])
                    
                    matched_count = 0
                    for s in studs:
                        k = (str(s.get("학년")), str(s.get("반")), str(s.get("이름")))
                        if k in old_new_map:
                            n_g, n_c, n_n = old_new_map[k]
                            s["학년"] = int(float(n_g)) if n_g.isdigit() else n_g
                            s["반"] = n_c
                            s["번호"] = int(float(n_n)) if n_n.isdigit() else n_n
                            
                            if s["학년"] == 3:
                                s["추가지원"] = "초3이용권"
                                if not s.get("1순위지원금") or s.get("1순위지원금") == "수익자":
                                    s["1순위지원금"] = "초3이용권"
                            else:
                                if s.get("추가지원") == "초3이용권":
                                    s["추가지원"] = ""
                                if s.get("1순위지원금") == "초3이용권":
                                    s["1순위지원금"] = "교육비대상자" if s.get("가구자격") == "교육비지원" else "수익자"
                                    
                            matched_count += 1
                            
                    for e in enrols:
                        k = (str(e.get("학년")), str(e.get("반")), str(e.get("이름")))
                        if k in old_new_map:
                            n_g, n_c, n_n = old_new_map[k]
                            e["학년"] = int(float(n_g)) if n_g.isdigit() else n_g
                            e["반"] = n_c
                            e["번호"] = int(float(n_n)) if n_n.isdigit() else n_n
                            
                    save_data(get_monthly_path("merged_students.json"), studs)
                    save_data(get_monthly_path("enrollments.json"), enrols)
                    
                    st.success(f"✅ 총 {matched_count}명의 학적이 새 학년/반으로 성공적으로 업데이트되었습니다! (초3이용권 자격 자동 갱신 포함)")
                    st.rerun()
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {str(e)}")

    st.markdown("---")
    st.subheader("📁 이전 통합 자료 백업 목록")
    if os.path.exists("archive"):
        archives = sorted(list(set(["_".join(f.split("_")[:2]) for f in os.listdir("archive") if f.endswith(".json")])), reverse=True)
        if archives:
            for arch in archives:
                st.text(f"🕒 백업 일시: {arch[:4]}년 {arch[4:6]}월 {arch[6:8]}일 {arch[9:11]}시 {arch[11:13]}분 {arch[13:15]}초")
        else:
            st.caption("저장된 백업 파일이 없습니다.")
    else:
        st.caption("저장된 백업 파일이 없습니다.")

with tab3:
    st.header("💰 3. 수강료 정산 관리")
    st.markdown("프로그램별 **수강료 및 재료비**를 확인하고 수정합니다. 3월 운영일수를 기준으로 수강료가 자동 산출됩니다.")
    
    if not os.path.exists(get_monthly_path("programs.json")):
        st.warning("먼저 [2. 기초자료] 탭에서 데이터를 업로드해주세요.")
    else:
        df_programs = pd.DataFrame(load_data(get_monthly_path("programs.json"), []))
        holidays = load_data("holidays.json", {})
        
        # 기본값 계산
        y = settings["year"]
        m = st.session_state.selected_month
        num_days = calendar.monthrange(y, m)[1]
        
        fee_data = []
        for _, row in df_programs.iterrows():
            prog_name = row.get("프로그램명", "")
            instructor = row.get("강사명", "")
            cap_str = str(row.get("수강정원", row.get("정원", "20")))
            try:
                cap = int("".join(filter(str.isdigit, cap_str)))
            except:
                cap = 20
                
            is_free = False
            for col in ["최종 수강료", "수강료", "비고", "프로그램명", "차시당단가", "차시당 단가"]:
                val = str(row.get(col, "")).strip().replace(" ", "")
                if "무료" in val:
                    is_free = True
                    break
                    
            if is_free:
                hourly = 0
            else:
                if cap <= 10:
                    hourly = settings.get("tuition_10", 3300)
                elif cap <= 15:
                    hourly = settings.get("tuition_15", 2200)
                else:
                    hourly = settings.get("tuition_20", 1650)
                
            days_str = str(row.get("운영요일", ""))
            days_list = [d.strip() for d in days_str.split(",") if d.strip()]
            kor_wd = ["월", "화", "수", "목", "금", "토", "일"]
            target_wds = [kor_wd.index(d) for d in days_list if d in kor_wd]
            
            session_count = 0
            for d in range(1, num_days + 1):
                chk_date = date(y, m, d)
                if chk_date.weekday() in target_wds:
                    if chk_date.strftime("%Y-%m-%d") not in holidays:
                        session_count += 1
                        
            auto_fee = hourly * session_count
            
            
            mat_fee_str = str(row.get("재료비", row.get("월재료비", row.get("월 재료비", "0"))))
            try:
                mat_fee = int("".join(filter(str.isdigit, mat_fee_str)))
            except:
                mat_fee = 0
            
            fee_data.append({
                "프로그램명": prog_name,
                "강사명": instructor,
                "수강정원": cap,
                "운영요일": days_str,
                f"{m}월 시수": session_count,
                "차시당 단가": hourly,
                "자동 산출 수강료": auto_fee,
                "최종 수강료": auto_fee,
                "재료비 차시당 단가": 0,
                "월 재료비": mat_fee
            })
            
        df_fees_base = pd.DataFrame(fee_data)
        
        saved_fees = load_data(get_monthly_path("program_fees.json"), [])
        if saved_fees:
            df_saved = pd.DataFrame(saved_fees)
            for _, srow in df_saved.iterrows():
                idx = df_fees_base[df_fees_base["프로그램명"] == srow["프로그램명"]].index
                if not idx.empty:
                    saved_hourly = srow.get("차시당 단가")
                    if pd.notna(saved_hourly):
                        df_fees_base.loc[idx[0], "차시당 단가"] = saved_hourly
                        session_count = df_fees_base.loc[idx[0], f"{m}월 시수"]
                        df_fees_base.loc[idx[0], "자동 산출 수강료"] = saved_hourly * session_count
                        
                    saved_mat_hourly = srow.get("재료비 차시당 단가")
                    if pd.notna(saved_mat_hourly):
                        df_fees_base.loc[idx[0], "재료비 차시당 단가"] = saved_mat_hourly
                        
                    df_fees_base.loc[idx[0], "최종 수강료"] = srow.get("최종 수강료", df_fees_base.loc[idx[0], "자동 산출 수강료"])
                    df_fees_base.loc[idx[0], "월 재료비"] = srow.get("월 재료비", df_fees_base.loc[idx[0], "월 재료비"])
        
        st.subheader("📝 프로그램별 수강료/재료비 설정")
        st.caption("✔️ **표 안의 [차시당 단가], [재료비 차시당 단가], [최종 수강료], [월 재료비] 금액칸을 클릭하여 자유롭게 수정해 보세요.**")
        st.info("💡 단가를 수정하고 '저장' 버튼을 누르면 최종 수강료/월 재료비가 자동으로 산출되어 반영됩니다. (직접 최종 금액을 입력해도 됩니다)")
        edited_fees = st.data_editor(
            df_fees_base,
            column_config={
                "프로그램명": st.column_config.TextColumn(disabled=True),
                "강사명": st.column_config.TextColumn(disabled=True),
                "수강정원": st.column_config.NumberColumn(disabled=True),
                "운영요일": st.column_config.TextColumn(disabled=True),
                f"{m}월 시수": st.column_config.NumberColumn(disabled=True),
                "차시당 단가": st.column_config.NumberColumn("차시당 단가(원)", disabled=False),
                "자동 산출 수강료": st.column_config.NumberColumn("자동 산출 수강료(원)", disabled=True),
                "최종 수강료": st.column_config.NumberColumn("최종 수강료(원)", disabled=False),
                "재료비 차시당 단가": st.column_config.NumberColumn("재료비 차시당 단가(원)", disabled=False),
                "월 재료비": st.column_config.NumberColumn("월 재료비(원)", disabled=False)
            },
            hide_index=True,
            use_container_width=True
        )
        
        if st.button("✅ 수강료 및 재료비 저장", type="primary"):
            for i, row in edited_fees.iterrows():
                base_row = df_fees_base.iloc[i]
                if row["차시당 단가"] != base_row["차시당 단가"]:
                    edited_fees.at[i, "최종 수강료"] = row["차시당 단가"] * row[f"{m}월 시수"]
                if row["재료비 차시당 단가"] != base_row["재료비 차시당 단가"]:
                    edited_fees.at[i, "월 재료비"] = row["재료비 차시당 단가"] * row[f"{m}월 시수"]
                    
            save_data(get_monthly_path("program_fees.json"), edited_fees.to_dict(orient="records"))
            st.success("✅ 프로그램별 수강료와 재료비가 저장되었습니다!")
            st.rerun()
            
        st.markdown("---")
        st.subheader("🧑‍🎓 학생별 수강료 정산 명세 및 소급 정산")
        
        if os.path.exists(get_monthly_path("enrollments.json")) and os.path.exists(get_monthly_path("merged_students.json")):
            df_enroll = pd.DataFrame(load_data(get_monthly_path("enrollments.json"), []))
            df_stud = pd.DataFrame(load_data(get_monthly_path("merged_students.json"), []))
            
            if not df_enroll.empty and not df_stud.empty and os.path.exists(get_monthly_path("program_fees.json")):
                df_prog_fees = pd.DataFrame(load_data(get_monthly_path("program_fees.json"), []))
                
                # 수강신청 명단 형식 확인
                # 엑셀의 형태가 '학년', '반', '이름', '프로그램', '운영요일' 등으로 세로로 나열되어 있는지 확인
                df_enroll.columns = df_enroll.columns.astype(str).str.strip()
                if "프로그램" in df_enroll.columns:
                    melted = df_enroll.rename(columns={"프로그램": "프로그램명"}).copy()
                elif "프로그램명" in df_enroll.columns:
                    melted = df_enroll.copy()
                else:
                    # 와이드 폼 (O 표시) 인 경우
                    id_vars = [c for c in df_enroll.columns if c in ["학년", "반", "번호", "이름"]]
                    melted = df_enroll.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
                    melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
                
                # 학생 통합정보와 병합 (자격상세, 가구자격 가져오기)
                if not melted.empty:
                    # 공백 제거
                    melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
                    df_prog_fees["프로그램명"] = df_prog_fees["프로그램명"].astype(str).str.strip()
                    
                    merge_keys = [k for k in ["학년", "반", "번호", "이름"] if k in df_stud.columns and k in melted.columns]
                    if merge_keys:
                        df_calc = pd.merge(melted, df_stud, on=merge_keys, how="left")
                    else:
                        df_calc = melted.copy()
                        df_calc["가구자격"] = "수익자"
                        
                    # 프로그램 수강료 정보와 병합
                    df_calc = pd.merge(df_calc, df_fees_base[["프로그램명", "강사명", "운영요일", f"{m}월 시수", "차시당 단가", "최종 수강료", "월 재료비"]], on="프로그램명", how="inner")
                    
                    # 결석/공결 입력 등을 위해 고유 ID 생성
                    df_calc["고유ID"] = df_calc["학년"].astype(str) + "-" + df_calc["반"].astype(str) + "-" + df_calc["이름"] + "_" + df_calc["프로그램명"]
                    
                    # 환급 내역 및 소급 정산 내역 불러오기
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
                    
                    display_cols = ["고유ID", "학년", "반", "이름", "프로그램명", "강사명", "운영요일", f"{m}월 시수", "차시당 단가", "가구자격", "총 금액", "지원금(면제)", "기본 징수액", "추가징수액", "소급환급액", "환급액", "환급사유", "최종 징수액"]
                    df_display = df_calc[[c for c in display_cols if c in df_calc.columns]].sort_values(by=["프로그램명", "학년", "반", "이름"])
                    
                    if not df_display.empty:
                        st.caption("✔️ 아래 표에서 **[환급액]**과 **[환급사유]**를 더블클릭하여 수정하고 하단의 저장 버튼을 누르세요. (예: 중도포기, 장기결석 등)")
                        
                        # 필터와 요약 정보를 나란히 배치
                        col_filter, col_summary = st.columns([1, 1])
                        with col_filter:
                            sel_prog = st.selectbox("특정 프로그램만 보기", ["전체보기"] + sorted(df_display["프로그램명"].unique().tolist()))
                            
                        if sel_prog != "전체보기":
                            df_display = df_display[df_display["프로그램명"] == sel_prog]
                            
                        total_charge = df_display["기본 징수액"].sum()
                        total_support = df_display["지원금(면제)"].sum()
                        total_retro_add = df_display["추가징수액"].sum()
                        total_retro_sub = df_display["소급환급액"].sum()
                        total_refund = df_display["환급액"].sum()
                        final_total = df_display["최종 징수액"].sum()
                        
                        with col_summary:
                            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                            st.info(f"💡 **합계** | 기본: **{total_charge:,.0f}원** | 환급: **{total_refund:,.0f}원** | 소급추가: **{total_retro_add:,.0f}원** | 소급환급: **{total_retro_sub:,.0f}원** | 최종 징수: **{final_total:,.0f}원**")
                            
                        edited_students = st.data_editor(
                            df_display,
                            column_config={
                                "고유ID": None, # 화면에서는 숨김 처리
                                "학년": st.column_config.NumberColumn(disabled=True),
                                "반": st.column_config.TextColumn(disabled=True),
                                "이름": st.column_config.TextColumn(disabled=True),
                                "프로그램명": st.column_config.TextColumn(disabled=True),
                                "강사명": st.column_config.TextColumn(disabled=True),
                                "운영요일": st.column_config.TextColumn(disabled=True),
                                f"{m}월 시수": st.column_config.NumberColumn(disabled=True),
                                "차시당 단가": st.column_config.NumberColumn("차시당 단가(원)", disabled=True),
                                "가구자격": st.column_config.TextColumn(disabled=True),
                                "총 금액": st.column_config.NumberColumn("총 금액(원)", disabled=True),
                                "지원금(면제)": st.column_config.NumberColumn("지원금(면제)(원)", disabled=True),
                                "기본 징수액": st.column_config.NumberColumn("기본 징수액(원)", disabled=True),
                                "환급액": st.column_config.NumberColumn("환급액(수정가능, 원)", min_value=0),
                                "환급사유": st.column_config.TextColumn("환급사유(수정가능)"),
                                "최종 징수액": st.column_config.NumberColumn("최종 징수액(원)", disabled=True)
                            },
                            height=600,
                            use_container_width=True,
                            hide_index=True
                        )
                        
                        col_dl, col_save = st.columns([1, 1])
                        with col_dl:
                            st.download_button("📥 현재 조회된 명단 엑셀 다운로드", data=to_excel(edited_students), file_name="수강료_징수명단.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_fee_1")
                        with col_save:
                            if st.button("💾 학생별 환급 및 최종 징수 내역 저장", type="primary"):
                                for _, r in edited_students.iterrows():
                                    uid = r["고유ID"]
                                    amt = r.get("환급액", 0)
                                    reason = r.get("환급사유", "")
                                    if pd.isna(amt): amt = 0
                                    if pd.isna(reason): reason = ""
                                    
                                    if amt > 0 or reason:
                                        refunds_data[uid] = {"환급액": int(amt), "환급사유": str(reason)}
                                    elif uid in refunds_data:
                                        del refunds_data[uid]
                                        
                                save_data(get_monthly_path("student_refunds.json"), refunds_data)
                                st.success("✅ 학생별 환급 및 정산 내역이 안전하게 저장되었습니다!")
                                st.rerun()
                    else:
                        st.warning("프로그램명 매칭에 실패했습니다. (프로그램명이 일치하는지 확인하세요)")
                else:
                    st.warning("수강신청 내역을 찾을 수 없습니다.")


        st.markdown("---")
        col_hdr1, col_hdr2 = st.columns([1, 1])
        with col_hdr1:
            st.markdown("##### 🔄 자격 변동에 따른 과거 월 소급 정산액 계산")
        with col_hdr2:
            st.markdown("##### 📌 이번 달 자격 변동 소급 정산 대상자 목록")
            
        col_info1, col_info2 = st.columns([1, 1])
        with col_info1:
            st.info("이 버튼을 누르면 현재 월 이전에 정산되었던 내역과 현재 자격을 비교하여 **추가 징수액**과 **소급 환급액**을 자동 계산합니다.")
            
        retro_rows = []
        has_retro_file = os.path.exists(get_monthly_path("retroactive_adjustments.json"))
        if has_retro_file:
            retro_data_view = load_data(get_monthly_path("retroactive_adjustments.json"), {})
            if retro_data_view:
                for uid, amounts in retro_data_view.items():
                    add_amt = amounts.get("추가징수액", 0)
                    sub_amt = amounts.get("소급환급액", 0)
                    if add_amt > 0 or sub_amt > 0:
                        parts = uid.split('_')
                        prog = parts[-1]
                        info = "_".join(parts[:-1])
                        info_parts = info.split('-')
                        if len(info_parts) >= 3:
                            grade, cls, name = info_parts[0], info_parts[1], "-".join(info_parts[2:])
                        else:
                            grade, cls, name = "", "", info
                        retro_rows.append({
                            "학년": grade,
                            "반": cls,
                            "이름": name,
                            "프로그램명": prog,
                            "추가 징수액(환수)": add_amt,
                            "소급 환급액": sub_amt
                        })
                        
        with col_info2:
            if retro_rows:
                st.info("💡 과거 내역을 대조하여 차액이 발생한 학생 목록을 아래 표에 표시합니다.")
            elif has_retro_file:
                st.info("💡 과거 내역을 대조한 결과, 소급 정산 대상자가 없습니다. (모두 동일)")
            else:
                st.info("💡 계산 버튼을 누르면 이 곳에 소급 정산 대상자 목록이 표시됩니다.")

        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("계산 실행 및 적용", use_container_width=True):
                retro_res = calculate_retroactive_adjustments(m, current_year, settings)
                save_data(get_monthly_path("retroactive_adjustments.json"), retro_res)
                st.success("✅ 자격 변동에 따른 소급 정산 내역이 계산되어 적용되었습니다!")
                st.rerun()
                
        with col_btn2:
            if retro_rows:
                df_retro_view = pd.DataFrame(retro_rows)
                st.dataframe(df_retro_view.style.format({"추가 징수액(환수)": "{:,.0f} 원", "소급 환급액": "{:,.0f} 원"}), hide_index=True, use_container_width=True)
            elif has_retro_file:
                st.button("결과 없음", disabled=True, use_container_width=True)
            else:
                st.button("결과 대기 중", disabled=True, use_container_width=True)
        
        st.markdown("<br>", unsafe_allow_html=True)

with tab4:
    st.header("👨‍🏫 4. 강사료 정산 관리")
    st.markdown("강사별 **실제 수업 차시**와 보강/결강 등을 반영하여 **최종 강사료**를 정산합니다.")
    
    if not os.path.exists(get_monthly_path("programs.json")):
        st.warning("먼저 [2. 기초자료] 탭에서 데이터를 업로드해주세요.")
    else:
        df_programs = pd.DataFrame(load_data(get_monthly_path("programs.json"), []))
        holidays = load_data("holidays.json", {})
        
        y = settings["year"]
        m = st.session_state.selected_month
        num_days = calendar.monthrange(y, m)[1]
        
        instructor_data = []
        for _, row in df_programs.iterrows():
            prog_name = row.get("프로그램명", "")
            instructor = row.get("강사명", "")
            instructor_type = str(row.get("강사구분", "외부")).strip()
            
            hourly_fee_str = str(row.get("차시당단가", ""))
            if pd.isna(hourly_fee_str) or hourly_fee_str.strip() == "" or hourly_fee_str.strip().lower() == "nan":
                hourly_fee = settings["ext_instructor_fee"] if instructor_type == "외부" else settings["int_instructor_fee"]
            else:
                try:
                    hourly_fee = int("".join(filter(str.isdigit, hourly_fee_str)))
                except:
                    hourly_fee = settings["ext_instructor_fee"] if instructor_type == "외부" else settings["int_instructor_fee"]
                    
            days_str = str(row.get("운영요일", ""))
            days_list = [d.strip() for d in days_str.split(",") if d.strip()]
            kor_wd = ["월", "화", "수", "목", "금", "토", "일"]
            target_wds = [kor_wd.index(d) for d in days_list if d in kor_wd]
            
            session_count = 0
            for d in range(1, num_days + 1):
                chk_date = date(y, m, d)
                if chk_date.weekday() in target_wds:
                    if chk_date.strftime("%Y-%m-%d") not in holidays:
                        session_count += 1
                        
            instructor_data.append({
                "강사명": instructor,
                "프로그램명": prog_name,
                "강사구분": instructor_type,
                "운영요일": days_str,
                f"{m}월 예정 차시": session_count,
                "차시당 단가": hourly_fee,
                "실제 수업 차시": session_count,
                "비고(보강/결강 등)": ""
            })
            
        df_inst_base = pd.DataFrame(instructor_data)
        
        # --- 수강료 수입 산출 (보전금 계산용) ---
        df_enroll = pd.DataFrame(load_data(get_monthly_path("enrollments.json"), []))
        df_prog_fees = pd.DataFrame(load_data(get_monthly_path("program_fees.json"), []))
        refunds_data = load_data(get_monthly_path("student_refunds.json"), {})
        program_incomes = {}
        program_support = {}
        program_support_g3 = {}
        program_support_ed = {}
        program_charge = {}
        
        if not df_enroll.empty and not df_prog_fees.empty:
            df_enroll.columns = df_enroll.columns.astype(str).str.strip()
            if "프로그램" in df_enroll.columns:
                melted = df_enroll.rename(columns={"프로그램": "프로그램명"}).copy()
            elif "프로그램명" in df_enroll.columns:
                melted = df_enroll.copy()
            else:
                id_vars = [c for c in df_enroll.columns if c in ["학년", "반", "번호", "이름"]]
                melted = df_enroll.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
                melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
            
            if not melted.empty:
                melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
                df_prog_fees["프로그램명"] = df_prog_fees["프로그램명"].astype(str).str.strip()
                df_calc = pd.merge(melted, df_prog_fees[["프로그램명", "최종 수강료"]], on="프로그램명", how="left")
                
                df_stud = pd.DataFrame(load_data(get_monthly_path("merged_students.json"), []))
                merge_keys = [k for k in ["학년", "반", "번호", "이름"] if k in df_stud.columns and k in df_calc.columns]
                if merge_keys:
                    df_calc = pd.merge(df_calc, df_stud, on=merge_keys, how="left")
                else:
                    df_calc["가구자격"] = "수익자"
                
                df_calc["고유ID"] = df_calc["학년"].astype(str) + "-" + df_calc["반"].astype(str) + "-" + df_calc["이름"] + "_" + df_calc["프로그램명"]
                
                for _, r in df_calc.iterrows():
                    p_name = r["프로그램명"]
                    fee = r.get("최종 수강료", 0)
                    qual = str(r.get("가구자격", ""))
                    if pd.isna(fee): fee = 0
                    
                    uid = r["고유ID"]
                    ref_amt = refunds_data.get(uid, {}).get("환급액", 0)
                    
                    if qual == "교육비지원":
                        support = fee
                        charge = 0
                    else:
                        support = 0
                        charge = fee
                        
                    actual_charge = max(0, charge - ref_amt)
                    
                    pri = str(r.get("1순위지원금", ""))
                    if support > 0:
                        if pri == "초3이용권":
                            program_support_g3[p_name] = program_support_g3.get(p_name, 0) + support
                        else:
                            program_support_ed[p_name] = program_support_ed.get(p_name, 0) + support
                            
                    program_support[p_name] = program_support.get(p_name, 0) + support
                    program_charge[p_name] = program_charge.get(p_name, 0) + actual_charge
                    program_incomes[p_name] = program_incomes.get(p_name, 0) + (support + actual_charge)
        # ------------------------------------
        
        saved_inst_fees = load_data(get_monthly_path("instructor_fees.json"), [])
        if saved_inst_fees:
            df_saved = pd.DataFrame(saved_inst_fees)
            for _, srow in df_saved.iterrows():
                idx = df_inst_base[(df_inst_base["강사명"] == srow.get("강사명", "")) & (df_inst_base["프로그램명"] == srow.get("프로그램명", ""))].index
                if not idx.empty:
                    df_inst_base.loc[idx[0], "실제 수업 차시"] = srow.get("실제 수업 차시", df_inst_base.loc[idx[0], f"{m}월 예정 차시"])
                    df_inst_base.loc[idx[0], "비고(보강/결강 등)"] = srow.get("비고(보강/결강 등)", "")
                    
        # Calculate totals dynamically for display
        df_inst_base["총 강사료(예상)"] = df_inst_base["실제 수업 차시"] * df_inst_base["차시당 단가"]
        
        # 보전금 계산 및 세부 통계
        df_inst_base["초3이용권 사용액"] = df_inst_base["프로그램명"].map(program_support_g3).fillna(0)
        df_inst_base["교육비지원 사용액"] = df_inst_base["프로그램명"].map(program_support_ed).fillna(0)
        df_inst_base["교육비지원대상 총액"] = df_inst_base["프로그램명"].map(program_support).fillna(0)
        df_inst_base["수익자 부담액"] = df_inst_base["프로그램명"].map(program_charge).fillna(0)
        df_inst_base["총 수강료 수입"] = df_inst_base["프로그램명"].map(program_incomes).fillna(0)
        df_inst_base["강사료 보전금"] = (df_inst_base["총 강사료(예상)"] - df_inst_base["총 수강료 수입"]).apply(lambda x: max(0, x))
        
        st.subheader("📝 강사료 산출 및 보전금 내역")
        st.caption("✔️ **표 안의 [실제 수업 차시]를 더블클릭하여 수정 후 [저장] 버튼을 누르면 총 강사료와 보전금이 재계산됩니다.**")
        # 합계 행 추가 (화면 표시용)
        total_row = pd.DataFrame([{
            "강사명": "합계",
            "프로그램명": "-",
            "강사구분": "-",
            "운영요일": "-",
            f"{m}월 예정 차시": df_inst_base[f"{m}월 예정 차시"].sum(),
            "차시당 단가": None,
            "총 강사료(예상)": df_inst_base["총 강사료(예상)"].sum(),
            "초3이용권 사용액": df_inst_base["초3이용권 사용액"].sum(),
            "교육비지원 사용액": df_inst_base["교육비지원 사용액"].sum(),
            "교육비지원대상 총액": df_inst_base["교육비지원대상 총액"].sum(),
            "수익자 부담액": df_inst_base["수익자 부담액"].sum(),
            "총 수강료 수입": df_inst_base["총 수강료 수입"].sum(),
            "강사료 보전금": df_inst_base["강사료 보전금"].sum(),
            "실제 수업 차시": df_inst_base["실제 수업 차시"].sum(),
            "비고(보강/결강 등)": ""
        }])
        df_display = pd.concat([df_inst_base, total_row], ignore_index=True)
        
        edited_inst = st.data_editor(
            df_display,
            column_config={
                "강사명": st.column_config.TextColumn(disabled=True),
                "프로그램명": st.column_config.TextColumn(disabled=True),
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
                "초3이용권 사용액", "교육비지원 사용액", "교육비지원대상 총액", "수익자 부담액", "총 강사료(예상)", "강사료 보전금"
            ]
            df_report = df_stats[[c for c in report_cols if c in df_stats.columns]].copy()
            
            st.dataframe(
                df_report,
                column_config={
                    "프로그램명": st.column_config.TextColumn("프로그램명"),
                    "강사명": st.column_config.TextColumn("강사명"),
                    "강사구분": st.column_config.TextColumn("강사구분"),
                    "총 수강료 수입": st.column_config.NumberColumn("전체 수강료 수입(원)"),
                    "초3이용권 사용액": st.column_config.NumberColumn("초3이용권(원)"),
                    "교육비지원 사용액": st.column_config.NumberColumn("교육비지원(원)"),
                    "교육비지원대상 총액": st.column_config.NumberColumn("교육비 총액(원)"),
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
                student_subsidies = {}
                
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
                        
                        merge_keys = [k for k in ["학년", "반", "번호", "이름"] if k in df_stud.columns and k in melted.columns]
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

                                student_key = str(r.get("학년", "")) + "-" + str(r.get("반", "")) + "-" + str(r.get("번호", "")) + "-" + str(r.get("이름", ""))
                                if student_key not in student_subsidies:
                                    pri1 = str(r.get("1순위지원금", "")).strip()
                                    pri2 = str(r.get("2순위지원금", "")).strip()
                                    
                                    limit1, limit2 = 0, 0
                                    name1, name2 = pri1, pri2
                                    
                                    for pol in settings.get("support_policies", []):
                                        pol_name = pol.get("자격명", "").strip()
                                        pol_limit = pol.get("한도액", 0)
                                        if pol_name == pri1 or (pri1 == "교육비대상자" and ("자유수강권" in pol_name or "교육비" in pol_name)):
                                            limit1 = pol_limit
                                            name1 = pol_name
                                        if pol_name == pri2 or (pri2 == "교육비대상자" and ("자유수강권" in pol_name or "교육비" in pol_name)):
                                            limit2 = pol_limit
                                            name2 = pol_name
                                            
                                    if limit1 == 0 and limit2 == 0 and dtl:
                                        for pol in settings.get("support_policies", []):
                                            if pol.get("자격명") == dtl:
                                                limit1 = pol.get("한도액", 0)
                                                name1 = dtl
                                                break
                                                
                                    if name1 in ["수익자", "", "nan", "None"]: name1 = ""
                                    if name2 in ["수익자", "", "nan", "None"]: name2 = ""
                                    
                                    if limit1 == 0 and limit2 > 0:
                                        limit1, limit2 = limit2, 0
                                        name1, name2 = name2, ""
                                        
                                    dtl_origin = str(r.get("자격상세", "")).strip()
                                    if dtl_origin in ["nan", "None", ""]: dtl_origin = "기타(수익자 등)"
                                        
                                    student_subsidies[student_key] = {
                                        "학년": str(r.get("학년", "")),
                                        "반": str(r.get("반", "")),
                                        "번호": str(r.get("번호", "")),
                                        "이름": str(r.get("이름", "")),
                                        "학생 자격(원본)": dtl_origin,
                                        "name1": name1, "limit1": limit1,
                                        "name2": name2, "limit2": limit2,
                                        "total_prev": 0, "total_curr": 0
                                    }
                                
                                curr_m_name = f"{st.session_state.selected_month}월"
                                if m_name == curr_m_name:
                                    student_subsidies[student_key]["total_curr"] += support
                                else:
                                    idx_m = months_list.index(m_num)
                                    idx_curr = months_list.index(st.session_state.selected_month)
                                    if idx_m < idx_curr:
                                        student_subsidies[student_key]["total_prev"] += support
                
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
                    
                    col_f1, col_f2 = st.columns([1, 2.5])
                    with col_f1:
                        st.download_button("📥 재원별 연간 누적 통계 엑셀 다운로드", data=to_excel(df_fund), file_name="연간_재원별_누적_통계.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stat_fund")
                    with col_f2:
                        st.info("💡 위 통계는 각 재원별(수익자, 지원금, 보전금) 지출 내역을 저장된 모든 월별 데이터를 합산하여 보여줍니다.")
                else:
                    st.info("💡 집계된 월별 정산 데이터가 없습니다.")

                st.markdown("---")
                st.subheader("💳 개인별 지원금 사용 현황표")
                if student_subsidies:
                    subsidy_rows = []
                    for s_info in student_subsidies.values():
                        name1 = s_info["name1"]
                        limit1 = s_info["limit1"]
                        name2 = s_info["name2"]
                        limit2 = s_info["limit2"]
                        total_prev = s_info["total_prev"]
                        total_curr = s_info["total_curr"]
                        
                        used1_prev = min(total_prev, limit1) if limit1 > 0 else total_prev
                        used1_curr = min(total_curr, max(0, limit1 - used1_prev)) if limit1 > 0 else total_curr
                        used2_prev = max(0, total_prev - used1_prev)
                        used2_curr = max(0, total_curr - used1_curr)
                        
                        if name1 or limit1 > 0 or used1_prev > 0 or used1_curr > 0:
                            subsidy_rows.append({
                                "학년": s_info["학년"],
                                "반": s_info["반"],
                                "번호": s_info["번호"],
                                "이름": s_info["이름"],
                                "학생 자격(원본)": s_info["학생 자격(원본)"],
                                "지원 정책명": name1 if name1 else "기타지원",
                                "배정된 총 한도액": limit1,
                                "누적 사용액(전월까지)": used1_prev,
                                "당월 추가 사용액": used1_curr,
                                "남은 잔여 금액": limit1 - used1_prev - used1_curr
                            })
                            
                        if name2 or limit2 > 0 or used2_prev > 0 or used2_curr > 0:
                            subsidy_rows.append({
                                "학년": s_info["학년"],
                                "반": s_info["반"],
                                "번호": s_info["번호"],
                                "이름": s_info["이름"],
                                "학생 자격(원본)": s_info["학생 자격(원본)"],
                                "지원 정책명": name2 if name2 else "초과사용/기타",
                                "배정된 총 한도액": limit2,
                                "누적 사용액(전월까지)": used2_prev,
                                "당월 추가 사용액": used2_curr,
                                "남은 잔여 금액": limit2 - used2_prev - used2_curr
                            })

                    df_subsidy = pd.DataFrame(subsidy_rows)
                    
                    def highlight_over_limit(row):
                        color = 'background-color: #fecaca; color: #991b1b; font-weight: bold' if row["남은 잔여 금액"] < 0 else ''
                        return [color] * len(row)
                        
                    format_subs = {c: "{:,.0f} 원" for c in ["배정된 총 한도액", "누적 사용액(전월까지)", "당월 추가 사용액", "남은 잔여 금액"]}
                    st.dataframe(
                        df_subsidy.style.apply(highlight_over_limit, axis=1).format(format_subs),
                        use_container_width=True, hide_index=True
                    )
                    st.download_button("📥 개인별 지원금 사용 현황 다운로드", data=to_excel(df_subsidy), file_name="지원금_사용현황.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stat_subsidy")
                else:
                    st.caption("이번 달까지 지원금을 사용한 학생 내역이 없습니다.")
                    
            except Exception as e:
                st.error(f"재원별 통계 산출 중 오류가 발생했습니다: {str(e)}")

    else:
        st.info("💡 4번 탭에서 [강사료 정산 및 보전금 내역 저장]을 완료해야 통계 보고서를 볼 수 있습니다.")

with tab6:
    st.header("📊 6. 통합 대시보드 및 학생 검색")
    st.markdown("전체 월의 정산 내역 및 학생별 히스토리를 확인합니다.")
    
    @st.cache_data
    def load_all_months_data(year):
        all_calc = []
        months_seq = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]
        for m in months_seq:
            y = year if m >= 3 else year + 1
            folder = f"data/{y}_{m:02d}"
            
            if not os.path.exists(folder):
                continue
                
            enrolls = load_data(os.path.join(folder, "enrollments.json"), [])
            prog_fees = load_data(os.path.join(folder, "program_fees.json"), [])
            studs = load_data(os.path.join(folder, "merged_students.json"), [])
            refunds = load_data(os.path.join(folder, "student_refunds.json"), {})
            retro = load_data(os.path.join(folder, "retroactive_adjustments.json"), {})
            
            if not enrolls or not studs or not prog_fees:
                continue
                
            df_en = pd.DataFrame(enrolls)
            df_st = pd.DataFrame(studs)
            df_pf = pd.DataFrame(prog_fees)
            
            if "프로그램명" in df_en.columns:
                melted = df_en.copy()
            elif "프로그램" in df_en.columns:
                melted = df_en.rename(columns={"프로그램": "프로그램명"})
            else:
                id_vars = [c for c in df_en.columns if c in ["학년", "반", "번호", "이름"]]
                melted = df_en.melt(id_vars=id_vars, var_name="프로그램명", value_name="신청여부")
                melted = melted[melted["신청여부"].astype(str).str.upper().isin(["O", "ㅇ", "Y", "1", "동그라미"])]
                
            if melted.empty: continue
            
            melted["프로그램명"] = melted["프로그램명"].astype(str).str.strip()
            df_pf["프로그램명"] = df_pf["프로그램명"].astype(str).str.strip()
            
            merge_keys = [k for k in ["학년", "반", "번호", "이름"] if k in df_st.columns and k in melted.columns]
            if merge_keys:
                df_calc = pd.merge(melted, df_st, on=merge_keys, how="left")
            else:
                df_calc = melted.copy()
                df_calc["가구자격"] = "수익자"
                
            if "최종 수강료" in df_pf.columns:
                df_calc = pd.merge(df_calc, df_pf[["프로그램명", "최종 수강료", "월 재료비"]], on="프로그램명", how="inner")
                df_calc["고유ID"] = df_calc["학년"].astype(str) + "-" + df_calc["반"].astype(str) + "-" + df_calc["이름"] + "_" + df_calc["프로그램명"]
                
                def calc_fees_export(row):
                    fee = row.get("최종 수강료", 0)
                    mat = row.get("월 재료비", 0)
                    if pd.isna(fee): fee = 0
                    if pd.isna(mat): mat = 0
                    qual = str(row.get("가구자격", ""))
                    total = fee + mat
                    if qual == "교육비지원":
                        support, charge, mat_charge = total, 0, 0
                    else:
                        support, charge, mat_charge = 0, total, mat
                    uid = row["고유ID"]
                    r_info = refunds.get(uid, {})
                    refund_amt = r_info.get("환급액", 0)
                    retro_info = retro.get(uid, {})
                    r_add = retro_info.get("추가징수액", 0)
                    r_sub = retro_info.get("소급환급액", 0)
                    base_final = max(mat_charge, charge - refund_amt)
                    final_charge = base_final + r_add - r_sub
                    return pd.Series([total, support, charge, r_add, r_sub, refund_amt, r_info.get("환급사유", ""), final_charge])
                    
                df_calc[["총 금액", "지원금(면제)", "기본 징수액", "추가징수액", "소급환급액", "환급액", "환급사유", "최종 징수액"]] = df_calc.apply(calc_fees_export, axis=1)
                df_calc["월"] = f"{m}월"
                df_calc["월순서"] = months_seq.index(m)
                
                all_calc.append(df_calc)
                
        if all_calc:
            return pd.concat(all_calc, ignore_index=True)
        return pd.DataFrame()
        
    all_data = load_all_months_data(settings["year"])
    
    if not all_data.empty:
        st.subheader("🔍 학생별 통합 검색")
        
        def format_student(x):
            g = str(x['학년']).replace(".0", "").strip()
            c = str(x['반']).replace(".0", "").strip()
            n = str(x.get('번호', '')).replace(".0", "").strip()
            if n.lower() in ["nan", "none", ""]: n = " "
            nm = str(x['이름']).strip()
            return f"{g}-{c}-{n}-{nm}"

        all_data["_gr_str"] = all_data["학년"].astype(str).str.replace(".0", "", regex=False).str.strip()
        all_data["_cl_str"] = all_data["반"].astype(str).str.replace(".0", "", regex=False).str.strip()
        all_data["_num_str"] = all_data["번호"].astype(str).str.replace(".0", "", regex=False).str.strip() if "번호" in all_data.columns else ""
        all_data["_nm_str"] = all_data["이름"].astype(str).str.strip()
        
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        grades = ["전체"] + sorted([g for g in all_data["_gr_str"].unique() if g and g.lower() != "nan"])
        with f_col1:
            sel_gr = st.selectbox("학년 필터", grades, key="tab6_gr")
            
        filtered_data = all_data.copy()
        if sel_gr != "전체":
            filtered_data = filtered_data[filtered_data["_gr_str"] == sel_gr]
            
        classes = ["전체"] + sorted([c for c in filtered_data["_cl_str"].unique() if c and c.lower() != "nan"])
        with f_col2:
            sel_cl = st.selectbox("반 필터", classes, key="tab6_cl")
            
        if sel_cl != "전체":
            filtered_data = filtered_data[filtered_data["_cl_str"] == sel_cl]
            
        nums = ["전체"] + sorted([n for n in filtered_data["_num_str"].unique() if n and n.lower() != "nan"])
        with f_col3:
            sel_num = st.selectbox("번호 필터", nums, key="tab6_num")
            
        if sel_num != "전체":
            filtered_data = filtered_data[filtered_data["_num_str"] == sel_num]
            
        names = ["전체"] + sorted([nm for nm in filtered_data["_nm_str"].unique() if nm and nm.lower() != "nan"])
        with f_col4:
            sel_nm = st.selectbox("이름 필터", names, key="tab6_nm")
            
        if sel_nm != "전체":
            filtered_data = filtered_data[filtered_data["_nm_str"] == sel_nm]

        if filtered_data.empty:
            student_list = ["전체 (선택안함)"]
        else:
            student_list = filtered_data.apply(format_student, axis=1).unique().tolist()
            student_list.sort()
            student_list.insert(0, "전체 (선택안함)")
        
        sel_stud = st.selectbox("학생을 선택하세요 (검색 가능)", student_list)
        
        if sel_stud != "전체 (선택안함)":
            parts = sel_stud.split("-")
            gr, cl, num, nm = parts[0], parts[1], parts[2], parts[3]
            
            stud_data = all_data[
                (all_data["학년"].astype(str).str.replace(".0", "", regex=False).str.strip() == gr) & 
                (all_data["반"].astype(str).str.replace(".0", "", regex=False).str.strip() == cl) & 
                (all_data["이름"].astype(str).str.strip() == nm)
            ].copy()
            stud_data = stud_data.sort_values(by=["월순서", "프로그램명"])
            
            display_cols = ["월", "프로그램명", "가구자격", "총 금액", "지원금(면제)", "최종 징수액", "환급액", "환급사유"]
            df_display = stud_data[display_cols].copy()
            
            format_dict = {c: "{:,.0f} 원" for c in ["총 금액", "지원금(면제)", "최종 징수액", "환급액"]}
            st.dataframe(df_display.style.format(format_dict), use_container_width=True, hide_index=True)
            
            col_down1, col_down2 = st.columns([1, 3])
            with col_down1:
                st.download_button("📥 학생 히스토리 엑셀 다운로드", data=to_excel(df_display), file_name=f"{sel_stud}_정산히스토리.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_stud_hist")
            
            total_charge = stud_data["최종 징수액"].sum()
            total_refund = stud_data["환급액"].sum()
            st.info(f"**{sel_stud}** 학생의 누적 최종 징수액: **{total_charge:,.0f}원** (누적 환급액: {total_refund:,.0f}원)")
        else:
            st.info("학생을 선택하면 월별 수강 내역 및 정산 히스토리가 표시됩니다.")
            
        st.markdown("---")
        st.subheader("📈 연간 추이 통합 통계")
        
        monthly_summary = all_data.groupby("월").agg(
            수강생연인원=("이름", "count"),
            총징수액=("최종 징수액", "sum"),
            총지원금=("지원금(면제)", "sum"),
            총환급액=("환급액", "sum")
        ).reset_index()
        
        months_seq_str = [f"{m}월" for m in [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]]
        monthly_summary["월순서"] = monthly_summary["월"].apply(lambda x: months_seq_str.index(x) if x in months_seq_str else 99)
        monthly_summary = monthly_summary.sort_values("월순서")
        
        df_monthly = monthly_summary[["월", "수강생연인원", "총징수액", "총지원금", "총환급액"]]
        st.dataframe(df_monthly.style.format({
            "총징수액": "{:,.0f} 원", "총지원금": "{:,.0f} 원", "총환급액": "{:,.0f} 원"
        }), use_container_width=True, hide_index=True)
        
        st.download_button("📥 월별 추이 엑셀 다운로드", data=to_excel(df_monthly), file_name="월별_통합_추이.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_monthly_trend")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.bar_chart(monthly_summary.set_index("월")["총징수액"])
            st.caption("월별 총 징수액 추이")
        with col_c2:
            st.line_chart(monthly_summary.set_index("월")["수강생연인원"])
            st.caption("월별 방과후 수강생(연인원) 추이")
            
    else:
        st.warning("등록된 월별 정산 데이터가 없습니다.")
