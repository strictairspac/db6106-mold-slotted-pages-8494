import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { table } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { navigate } from "../router/router.js";
import { el } from "../utils/dom.js";

function queueForm(config, selected) {
  const form = el("form", {class: "queue-form"},
    field(config.parameter_label, el("input", {
      name: "parameter", type: "number", min: 1, max: config.max_parameter, required: true, value: config.default_parameter,
    })),
    el("button", {type: "submit"}, "提交执行"), errorText());
  submit(form, async values => {
    const run = await api.enqueue(selected.id, {parameter: Number(values.get("parameter"))});
    navigate(`runs/${run.id}`);
  });
  return form;
}

function clearNoteForm(selected) {
  const code = el("input", {
    id: "order-no", name: "code", type: "text", required: true, maxlength: 48,
    autocomplete: "off", value: selected?.code || "", "data-testid": "clear-order-no",
  });
  const historyNo = el("input", {
    id: "history-no", name: "history_no", type: "text", required: true, maxlength: 24,
    pattern: "[A-Za-z0-9_-]{1,24}", autocomplete: "off",
    placeholder: "履历号，例如 GM-071", "data-testid": "clear-history-no",
  });
  const success = el("p", {class: "state-done", role: "status", "data-testid": "clear-note-success"});
  const form = el("form", {
    id: "clear-note-form", "data-testid": "clear-note-form",
  },
    el("div", {class: "clear-note-grid"},
      field("单号", code, "变更单编号；只清除这张单。"),
      field("履历号", historyNo, "与单号共同定位整条备注。")),
    el("p", {class: "help-text"}, "同履历号的其他变更单不会被改动。原文会从原单和已生成的完工凭据中同时清除，并以等 UTF-8 字节掩码占位，保证重放槽号和偏移不变。"),
    el("button", {type: "submit", "data-testid": "clear-note-button"}, "清除整条备注"),
    errorText(), success);

  submit(form, async values => {
    success.textContent = "";
    const enteredCode = values.get("code");
    const sameOrder = selected && (enteredCode === selected.code || enteredCode === String(selected.id));
    const pre = sameOrder ? document.querySelector("[data-testid='case-payload']") : null;
    const payloadInput = sameOrder ? document.querySelector("#case-form textarea[name='payload']") : null;
    const safeView = JSON.stringify({
      redaction: {status: "pending", message: "该单正在清除整条备注，完成后才恢复查阅。"},
    }, null, 2);
    if (pre) pre.textContent = safeView;
    if (payloadInput) payloadInput.value = safeView;
    try {
      const result = await api.clearNote({
        code: enteredCode,
        history_no: values.get("history_no"),
      });
      const message = `已清除 ${result.operation_count} 处原单备注、${result.run_count} 份完工凭据中的原文。`;
      success.textContent = message;
      if (result.case_id === selected?.id) {
        const fresh = await api.case(result.case_id);
        if (pre) {
          pre.textContent = JSON.stringify(fresh.payload, null, 2);
          pre.closest("details")?.setAttribute("open", "");
        }
        if (payloadInput) payloadInput.value = JSON.stringify(fresh.payload, null, 2);
      } else if (result.case_id) {
        sessionStorage.setItem("workbench:flash", message);
        navigate(`cases/${result.case_id}`);
      }
    } catch (error) {
      if (pre && selected?.id) {
        try {
          const fresh = await api.case(selected.id);
          const text = JSON.stringify(fresh.payload, null, 2);
          if (pre) pre.textContent = text;
          if (payloadInput) payloadInput.value = text;
        } catch {
          // Keep the safe pending placeholder if recovery could not be confirmed.
        }
      }
      throw error;
    }
  });
  return form;
}

function registration(config, selected) {
  const data = selected ? JSON.stringify(selected.payload, null, 2) : "{}";
  const form = el("form", {id: "case-form"},
    field("名称", el("input", {name: "title", required: true, minlength: 2, maxlength: 120, value: selected ? `${selected.title} · 复演` : ""})),
    field("说明", el("input", {name: "description", maxlength: 420, value: selected?.description || ""})),
    field(`${config.unit}内容`, el("textarea", {name: "payload", spellcheck: "false", required: true, rows: 12}, data),
      selected ? "可以保留演示数据，也可以编辑 JSON 后保存。" : "输入业务 JSON。"),
    errorText(), el("button", {type: "submit"}, "保存资料"));
  submit(form, async values => {
    let payload;
    try {
      payload = JSON.parse(values.get("payload"));
    } catch {
      throw new Error("资料 JSON 无法解析，请检查括号、引号和逗号");
    }
    const entry = await api.createCase({title: values.get("title"), description: values.get("description"), payload});
    navigate(`cases/${entry.id}`);
  });
  return form;
}

export async function casesPage(config, user, route) {
  const cases = await api.cases();
  let selected = cases.find(item => item.id === route.id) ?? cases.at(-1);
  if (route.id) {
    try {
      selected = await api.case(route.id);
    } catch {
      // Keep the safe list projection, which hides an unfinished clear.
    }
  }
  const operator = user.role === "operator";
  const pending = selected?.redaction_status === "pending";
  const cleared = selected?.redaction_status === "done";
  const flash = sessionStorage.getItem("workbench:flash");
  if (flash) sessionStorage.removeItem("workbench:flash");
  return el("div", {class: "page", "data-page": "cases"},
    pageHeading(config.modules[1], `${config.unit} · ${config.fixture}`),
    flash ? el("p", {class: "state-done", role: "status", "data-testid": "clear-flash"}, flash) : null,
    section("资料目录", cases.length ? table(["单号", "名称", "说明", "操作"], cases.map(item =>
      [item.code, item.title, item.description,
        el("a", {href: `#cases/${item.id}`, "aria-current": item.id === selected?.id ? "true" : null}, "选用")]), "资料目录") :
      empty("这里还没有资料。")),
    operator ? section("清除工票备注", clearNoteForm(selected)) : null,
    el("div", {class: "split case-split"},
      section(selected ? selected.title : "等待选择资料", selected ?
        [pending ? el("p", {role: "alert", "data-testid": "case-clearing"}, "该单正在清除整条备注，完成后才恢复查阅。") : null,
          cleared ? el("p", {class: "state-done", "data-testid": "case-cleared"}, "该单履历备注已清除，掩码保持 UTF-8 字节数不变。") : null,
          el("p", {}, selected.description), operator && !pending ? queueForm(config, selected) : empty("当前账号可查看此资料。"),
          el("details", {}, el("summary", {}, "查看业务数据"),
            el("pre", {"data-testid": "case-payload"}, JSON.stringify(selected.payload, null, 2)))] :
        empty("先登记一条资料，再提交执行。")),
      operator ? section("登记新资料", registration(config, selected)) : null));
}
