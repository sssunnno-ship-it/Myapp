import html
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

DATA_FILE = Path(__file__).parent / "data" / "items.json"
MAX_NAME_LENGTH = 50
MIN_QTY, MAX_QTY = 1, 99


# ---------- 저장소 ----------
# 파일이 유일한 원본이다. 탭/기기마다 세션이 따로 있으므로, 변경할 때마다
# 파일에서 최신 목록을 다시 읽고 그 위에 변경을 적용해 저장한다.

@st.cache_resource
def file_lock():
    """모든 세션이 공유하는 파일 잠금."""
    return threading.RLock()


def normalize_item(raw):
    """저장된 아이템을 현재 스키마에 맞춘다. 형식이 잘못됐으면 None."""
    if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
        return None
    try:
        qty = int(raw.get("quantity", MIN_QTY))
    except (TypeError, ValueError):
        qty = MIN_QTY
    return {
        "id": str(raw.get("id") or uuid.uuid4()),
        "name": str(raw["name"]).strip()[:MAX_NAME_LENGTH],
        "checked": bool(raw.get("checked", False)),
        "created_at": str(raw.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        "quantity": min(max(qty, MIN_QTY), MAX_QTY),
    }


def load_items():
    """data/items.json에서 아이템 목록을 읽는다.
    파일이 없으면 빈 리스트, 깨졌으면 items.json.bak으로 백업한 뒤 빈 리스트."""
    with file_lock():
        try:
            with DATA_FILE.open(encoding="utf-8") as f:
                raw_items = json.load(f)
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw_items = None
        if not isinstance(raw_items, list):
            shutil.copyfile(DATA_FILE, DATA_FILE.with_suffix(".json.bak"))
            return []
    return [item for item in map(normalize_item, raw_items) if item]


def save_items(items):
    """아이템 목록을 임시 파일에 쓴 뒤 교체해, 읽는 쪽이 반쯤 쓴 파일을 보지 않게 한다."""
    with file_lock():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def mutate(change):
    """최신 목록에 change(items) -> items를 적용해 저장한다.
    변경이 일어나면 열려 있던 전체 삭제 확인창은 닫는다."""
    st.session_state.confirm_clear = False
    with file_lock():
        new_items = change(load_items())
        save_items(new_items)
    st.session_state.shopping_items = new_items


def update_item(item_id, **fields):
    """id가 같은 아이템의 필드를 바꾼다. 다른 탭에서 이미 삭제됐으면 아무것도 하지 않는다."""
    def change(items):
        for item in items:
            if item["id"] == item_id:
                item.update(fields)
        return items
    mutate(change)


def init_state():
    """세션 상태를 초기화하고, 매 실행마다 파일에서 최신 목록을 불러온다."""
    defaults = {"editing_id": None, "confirm_clear": False, "add_error": None, "edit_error": None}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    st.session_state.shopping_items = load_items()
    if st.session_state.editing_id and not find_item(st.session_state.editing_id):
        on_cancel_edit()


def items():
    return st.session_state.shopping_items


def find_item(item_id):
    return next((item for item in items() if item["id"] == item_id), None)


def validate(name, qty):
    """이름과 수량을 검사해 (정리된 이름, 에러메시지)를 돌려준다."""
    name = (name or "").strip()
    if not name:
        return name, "아이템 이름을 입력해주세요."
    if len(name) > MAX_NAME_LENGTH:
        return name, f"아이템 이름은 {MAX_NAME_LENGTH}자 이하로 입력해주세요. (현재 {len(name)}자)"
    if qty is None or not MIN_QTY <= qty <= MAX_QTY:
        return name, f"수량은 {MIN_QTY}~{MAX_QTY} 사이로 입력해주세요."
    return name, None


# ---------- 콜백 (상태 변경은 모두 여기서) ----------

def on_add():
    """F-1: 입력 폼의 값으로 아이템을 추가한다."""
    qty = st.session_state.new_qty
    name, error = validate(st.session_state.new_name, qty)
    st.session_state.add_error = error
    if error:
        return
    new_item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "checked": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "quantity": int(qty),
    }
    mutate(lambda items: items + [new_item])


def on_start_edit(item_id):
    """F-2: 해당 아이템을 편집 모드로 전환한다."""
    item = find_item(item_id)
    st.session_state.confirm_clear = False
    if not item:
        return
    st.session_state.editing_id = item_id
    st.session_state.edit_error = None
    st.session_state[f"edit_name_{item_id}"] = item["name"]
    st.session_state[f"edit_qty_{item_id}"] = item["quantity"]


def on_save_edit(item_id):
    """F-2: 편집 내용을 저장한다. 값이 올바르지 않으면 저장하지 않는다."""
    qty = st.session_state[f"edit_qty_{item_id}"]
    name, error = validate(st.session_state[f"edit_name_{item_id}"], qty)
    st.session_state.edit_error = error
    if error:
        return
    update_item(item_id, name=name, quantity=int(qty))
    st.session_state.editing_id = None


def on_cancel_edit():
    st.session_state.editing_id = None
    st.session_state.edit_error = None


def on_delete(item_id):
    """F-3: 아이템을 삭제한다."""
    mutate(lambda items: [i for i in items if i["id"] != item_id])
    if st.session_state.editing_id == item_id:
        on_cancel_edit()


def on_toggle(item_id):
    """F-4: 체크 상태를 체크박스 값과 맞춘다."""
    update_item(item_id, checked=st.session_state[f"check_{item_id}"])


def on_clear_checked():
    """F-7: 완료된 아이템을 모두 삭제한다."""
    mutate(lambda items: [i for i in items if not i["checked"]])
    if not find_item(st.session_state.editing_id):
        on_cancel_edit()


def on_request_clear_all(confirm):
    st.session_state.confirm_clear = confirm


def on_clear_all():
    """F-8: 전체 아이템을 삭제한다."""
    mutate(lambda items: [])
    on_cancel_edit()


# ---------- 화면 ----------

CSS = """
<style>
/* 좁은 화면에서도 열이 세로로 쌓이지 않게 한 줄 유지 */
[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
[data-testid="stColumn"] { min-width: 0 !important; }
[data-testid="stColumn"]:has(.stButton, .stFormSubmitButton) { flex: 0 0 auto !important; width: auto !important; }
[data-testid="stColumn"]:has(.stCheckbox) { flex: 0 0 1.75rem !important; width: 1.75rem !important; }
.stButton button, .stFormSubmitButton button { min-height: 40px; min-width: 40px; white-space: nowrap; }
[class*="st-key-row_"] {
    border-bottom: 1px solid rgba(128, 128, 128, 0.2);
    padding: 0.15rem 0;
}
.item-name { font-size: 1.05rem; line-height: 1.4; overflow-wrap: anywhere; }
.item-name.done { text-decoration: line-through; opacity: 0.5; }
.item-qty { margin-left: 0.35rem; font-size: 0.85rem; opacity: 0.7; }
</style>
"""


def name_html(item):
    """아이템 이름(+수량)을 HTML로 만든다. 사용자 입력은 이스케이프한다."""
    qty = f'<span class="item-qty">×{item["quantity"]}</span>' if item["quantity"] > 1 else ""
    done = " done" if item["checked"] else ""
    return f'<div class="item-name{done}">{html.escape(item["name"])}{qty}</div>'


def render_header():
    """제목과 F-6 진행 현황. 아이템이 없으면 진행 현황은 숨긴다."""
    st.title("🛒 쇼핑리스트")
    total = len(items())
    if not total:
        return
    done = sum(item["checked"] for item in items())
    st.progress(done / total, text=f"{total}개 중 {done}개 완료")


def render_input():
    """F-1: 아이템 입력 폼."""
    with st.form("add_form", clear_on_submit=True, border=False):
        col_name, col_qty, col_add = st.columns([5, 2, 1], vertical_alignment="bottom")
        # 길이·수량 범위는 위젯이 아니라 validate()에서 검사한다.
        # 위젯 제한은 붙여넣기를 통째로 무시하거나 범위 밖 숫자를 조용히 되돌린다.
        col_name.text_input("아이템", key="new_name", placeholder="아이템 입력...")
        col_qty.number_input("수량", key="new_qty", value=1, step=1)
        col_add.form_submit_button("추가", type="primary", on_click=on_add)
    if st.session_state.add_error:
        st.warning(st.session_state.add_error)
        st.session_state.add_error = None


def render_edit_row(item):
    item_id = item["id"]
    col_name, col_qty, col_save, col_cancel = st.columns([5, 2, 1, 1], vertical_alignment="center")
    col_name.text_input("이름 수정", key=f"edit_name_{item_id}", label_visibility="collapsed")
    col_qty.number_input("수량", key=f"edit_qty_{item_id}", step=1, label_visibility="collapsed")
    col_save.button("저장", key=f"save_{item_id}", type="primary", on_click=on_save_edit, args=(item_id,))
    col_cancel.button("취소", key=f"cancel_{item_id}", on_click=on_cancel_edit)
    if st.session_state.edit_error:
        st.warning(st.session_state.edit_error)


def render_item_row(item):
    item_id = item["id"]
    col_check, col_name, col_edit, col_delete = st.columns([1, 8, 1, 1], vertical_alignment="center")
    # 다른 탭에서 바뀐 체크 상태가 위젯에 남은 값보다 우선하도록 매번 맞춘다.
    st.session_state[f"check_{item_id}"] = item["checked"]
    col_check.checkbox(
        "완료",
        key=f"check_{item_id}",
        on_change=on_toggle,
        args=(item_id,),
        label_visibility="collapsed",
    )
    col_name.html(name_html(item))
    col_edit.button("✏️", key=f"edit_{item_id}", help="수정", on_click=on_start_edit, args=(item_id,))
    col_delete.button("🗑️", key=f"delete_{item_id}", help="삭제", on_click=on_delete, args=(item_id,))


def render_list():
    """미완료 항목을 위, 완료 항목을 아래에 보여준다 (저장 순서는 그대로)."""
    if not items():
        st.info("아직 아이템이 없어요. 위에서 추가해보세요!")
        return
    for item in sorted(items(), key=lambda i: i["checked"]):
        with st.container(key=f"row_{item['id']}"):
            if item["id"] == st.session_state.editing_id:
                render_edit_row(item)
            else:
                render_item_row(item)


def render_footer():
    """F-7, F-8: 일괄 삭제 버튼."""
    if not items():
        return
    has_checked = any(item["checked"] for item in items())
    if st.session_state.confirm_clear:
        st.warning("정말 전체 삭제할까요?")
        col_yes, col_no, _ = st.columns([1, 1, 3])
        col_yes.button("삭제", key="confirm_clear_yes", type="primary", on_click=on_clear_all)
        col_no.button("취소", key="confirm_clear_no", on_click=on_request_clear_all, args=(False,))
        return
    col_clear, col_all, _ = st.columns([1, 1, 1])
    col_clear.button("완료 항목 지우기", on_click=on_clear_checked, disabled=not has_checked)
    col_all.button("전체 삭제", on_click=on_request_clear_all, args=(True,))


def main():
    st.set_page_config(page_title="쇼핑리스트", page_icon="🛒")
    init_state()
    st.html(CSS)
    render_header()
    render_input()
    render_list()
    render_footer()


if __name__ == "__main__":
    main()
