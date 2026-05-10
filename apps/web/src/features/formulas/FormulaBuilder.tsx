import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Info, Sigma, X } from "lucide-react";
import type { CustomMetricDefinition } from "../../api";
import { metricDescription, metricFormula, metricLabel, type SelectOption } from "../../domain";
import { Field } from "../../components/ui";
import { mutationError } from "../../workbench";
import { emitToast } from "../notifications/toast";
import { DEFAULT_CUSTOM_METRICS } from "./defaultCustomMetrics";

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function MetricInfoPopover({ metric }: { metric: SelectOption }) {
  const iconRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<number | null>(null);
  const pinnedOpen = useRef(false);
  const [position, setPosition] = useState<{ left: number; top: number; width: number; maxHeight: number; placement: "top" | "bottom" } | null>(null);
  const metricName = metric.value;
  const description = metric.description || metricDescription(metricName);
  const formula = metric.formula || metricFormula(metricName);
  const label = metric.label || metricLabel(metricName);
  const clearCloseTimer = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  const close = () => {
    clearCloseTimer();
    pinnedOpen.current = false;
    setPosition(null);
  };
  const scheduleClose = () => {
    if (pinnedOpen.current) return;
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => setPosition(null), 120);
  };
  const open = () => {
    clearCloseTimer();
    const rect = iconRef.current?.getBoundingClientRect();
    if (!rect) return;
    const gutter = 12;
    const width = Math.min(420, window.innerWidth - gutter * 2);
    const left = clamp(rect.right - width, gutter, Math.max(gutter, window.innerWidth - width - gutter));
    const spaceBelow = window.innerHeight - rect.bottom - gutter;
    const spaceAbove = rect.top - gutter;
    const placement: "top" | "bottom" = spaceBelow < 260 && spaceAbove > spaceBelow ? "top" : "bottom";
    const availableHeight = Math.max(180, placement === "bottom" ? spaceBelow - 8 : spaceAbove - 8);
    setPosition({
      left,
      top: placement === "bottom" ? rect.bottom + 8 : rect.top - 8,
      width,
      maxHeight: Math.min(360, availableHeight),
      placement,
    });
  };
  useEffect(() => {
    if (!position) return undefined;
    const reposition = () => open();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (iconRef.current?.contains(target) || popoverRef.current?.contains(target)) return;
      close();
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      clearCloseTimer();
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [position?.left, position?.top, position?.placement]);
  const togglePinned = () => {
    if (position && pinnedOpen.current) {
      close();
      return;
    }
    pinnedOpen.current = true;
    open();
  };
  const popover = position ? createPortal(
    <div
      ref={popoverRef}
      className={`metric-info-popover ${position.placement}`}
      role="tooltip"
      style={{ left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight }}
      onPointerEnter={clearCloseTimer}
      onPointerLeave={scheduleClose}
    >
      <b>{label}</b>
      {description && <span>{description}</span>}
      <MetricFormulaMath metricName={metricName} fallback={formula} />
      <small>Формула применяется только к текущему выбранному срезу.</small>
    </div>,
    document.body,
  ) : null;
  return (
    <span className="metric-info-popover-wrap">
      <button
        ref={iconRef}
        type="button"
        className="metric-info-icon"
        aria-label={`Описание показателя ${label}`}
        aria-expanded={Boolean(position)}
        onClick={togglePinned}
        onFocus={open}
        onBlur={scheduleClose}
        onPointerEnter={open}
        onPointerLeave={scheduleClose}
      >
        <Info size={14} />
      </button>
      {popover}
    </span>
  );
}

export function MetricFormulaMath({ metricName, fallback }: { metricName: string; fallback: string }) {
  const markup = metricFormulaMarkup(metricName);
  if (markup) return <span className="formula-math" dangerouslySetInnerHTML={{ __html: markup }} />;
  return <code className="formula-fallback">{fallback}</code>;
}

export function metricLabelFor(metricName: string, labels?: Record<string, string>) {
  return labels?.[metricName] ?? metricLabel(metricName);
}

const FORMULA_VARIABLES = [
  { token: "p", label: "Публикации" },
  { token: "c", label: "Цитирования" },
  { token: "c_frac", label: "Долевые цитирования" },
  { token: "cpp", label: "Средняя цитируемость" },
  { token: "h", label: "Индекс Хирша" },
  { token: "i10", label: "Работы с 10+ цитированиями" },
  { token: "g", label: "Индекс g" },
  { token: "m_local", label: "Индекс m" },
  { token: "f5", label: "Работы с 5+ цитированиями" },
  { token: "fm5", label: "Долевой вклад в работы с 5+ цитированиями" },
  { token: "lrdi", label: "Индекс устойчивости" },
  { token: "pr_p", label: "Процентиль публикаций" },
  { token: "pr_h", label: "Процентиль Хирша" },
  { token: "pr_c_frac", label: "Процентиль долевых цитирований" },
  { token: "pr_g", label: "Процентиль g-индекса" },
];

const FORMULA_FUNCTIONS = ["sqrt()", "log1p()", "log()", "exp()", "pow()", "min()", "max()", "abs()", "round()", "floor()", "ceil()"];
const FORMULA_FUNCTION_NAMES = new Set(FORMULA_FUNCTIONS.map((item) => item.replace("()", "")));

export function CustomMetricBuilder({
  metrics,
  setMetrics,
  onSaveMetric,
  onDeleteMetric,
  persistenceReady,
  selectedMetrics,
  setSelectedMetrics,
  activeMetric,
  setActiveMetric,
}: {
  metrics: CustomMetricDefinition[];
  setMetrics: (value: CustomMetricDefinition[]) => void;
  onSaveMetric: (value: CustomMetricDefinition) => Promise<unknown>;
  onDeleteMetric: (id: string) => Promise<unknown>;
  persistenceReady: boolean;
  selectedMetrics: string[];
  setSelectedMetrics: (value: string[]) => void;
  activeMetric: string;
  setActiveMetric: (value: string) => void;
}) {
  const [draft, setDraft] = useState<CustomMetricDefinition>({
    id: "",
    label: "",
    description: "",
    expression: DEFAULT_CUSTOM_METRICS[0].expression,
  });
  const addToken = (token: string) => {
    const current = draft.expression.trim();
    const suffix = token.endsWith("()") ? `${token.slice(0, -1)}` : token;
    const needsOperator = Boolean(current) && !/[+\-*/%(,\s]$/.test(current);
    const next = `${current}${needsOperator ? " + " : current ? " " : ""}${suffix}`.trim();
    setDraft({ ...draft, expression: next });
  };
  const addMetric = async () => {
    const expression = draft.expression.trim();
    if (!expression) {
      emitToast({ title: "Формула не добавлена", message: "Введите математическое выражение по доступным полям.", tone: "error" });
      return;
    }
    const validationError = validateFormulaExpression(expression);
    if (validationError) {
      emitToast({ title: "Формула не добавлена", message: validationError, tone: "error" });
      return;
    }
    const label = draft.label.trim() || `Собственная формула ${metrics.length + 1}`;
    const id = safeCustomMetricId(draft.id || label, metrics.length + 1);
    if (metrics.some((item) => item.id === id)) {
      emitToast({ title: "Формула не добавлена", message: "Формула с таким идентификатором уже есть. Измените короткое имя.", tone: "error" });
      return;
    }
    const nextMetric = { id, label, description: draft.description?.trim() || "Собственная формула по данным выбранного среза.", expression };
    try {
      if (persistenceReady) await onSaveMetric(nextMetric);
    } catch (error) {
      emitToast({ title: "Формула не сохранена", message: mutationError(error), tone: "error" });
      return;
    }
    setMetrics([...metrics.filter((item) => item.id !== id), nextMetric]);
    setSelectedMetrics([...new Set([...selectedMetrics, id])]);
    setActiveMetric(id);
    setDraft({ id: "", label: "", description: "", expression: "" });
    emitToast({ title: "Формула добавлена", message: `Показатель «${label}» включен в таблицу и графики.`, tone: "success" });
  };
  const removeMetric = async (id: string) => {
    try {
      if (persistenceReady) await onDeleteMetric(id);
    } catch (error) {
      emitToast({ title: "Формула не удалена", message: mutationError(error), tone: "error" });
      return;
    }
    setMetrics(metrics.filter((item) => item.id !== id));
    setSelectedMetrics(selectedMetrics.filter((item) => item !== id));
    if (activeMetric === id) setActiveMetric("h");
  };
  const resetMetrics = () => {
    const defaultIds = DEFAULT_CUSTOM_METRICS.map((item) => item.id);
    setMetrics(DEFAULT_CUSTOM_METRICS);
    setSelectedMetrics([...new Set([...selectedMetrics.filter((item) => !item.startsWith("custom_")), ...defaultIds])]);
    if (activeMetric.startsWith("custom_")) setActiveMetric(defaultIds[0] ?? "h");
    setDraft({ id: "", label: "", description: "", expression: DEFAULT_CUSTOM_METRICS[0].expression });
    emitToast({ title: "Формулы сброшены", message: "Возвращен пример собственной формулы по умолчанию.", tone: "info" });
  };
  return (
    <div className="formula-builder">
      <div className="formula-builder-head">
        <div>
          <h3>Калькулятор наукометрического показателя</h3>
          <p>Составьте выражение из показателей авторов. Поля `pr_...` означают процентиль 0–1 внутри текущей выборки, поэтому результат удобно сравнивать на общей шкале.</p>
        </div>
        <button type="button" onClick={resetMetrics}>Сбросить формулы</button>
      </div>
      <div className="formula-example">
        <b>Пример:</b>
        <code>100 * (pr_p * pr_h * pr_c_frac) ** (1 / 3)</code>
        <span>Это интегральный рейтинг по публикациям, индексу Хирша и долевым цитированиям.</span>
      </div>
      <div className="formula-form-grid">
        <Field label="Название">
          <input value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} placeholder="Например: Мой рейтинг" />
        </Field>
        <Field label="Короткое имя">
          <input value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value })} placeholder="custom_my_rating" />
        </Field>
      </div>
      <Field label="Описание">
        <input value={draft.description ?? ""} onChange={(event) => setDraft({ ...draft, description: event.target.value })} placeholder="Что показывает формула и когда ее применять" />
      </Field>
      <Field label="Формула">
        <textarea value={draft.expression} onChange={(event) => setDraft({ ...draft, expression: event.target.value })} rows={3} spellCheck={false} />
      </Field>
      <div className="formula-token-section">
        <b>Поля данных</b>
        <div className="formula-token-grid">
          {FORMULA_VARIABLES.map((item) => (
            <button type="button" className="choice-pill" key={item.token} onClick={() => addToken(item.token)} title={item.label}>
              {item.token}
            </button>
          ))}
        </div>
      </div>
      <div className="formula-token-section">
        <b>Функции</b>
        <div className="formula-token-grid compact">
          {FORMULA_FUNCTIONS.map((item) => (
            <button type="button" className="choice-pill" key={item} onClick={() => addToken(item)}>
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="formula-actions">
        <button type="button" className="primary" onClick={addMetric}><Sigma size={16} /> Добавить формулу</button>
      </div>
      {metrics.length > 0 && (
        <div className="custom-metric-list">
          {metrics.map((item) => {
            const enabled = selectedMetrics.includes(item.id) || activeMetric === item.id;
            return (
              <div key={item.id} className={enabled ? "custom-metric-row active" : "custom-metric-row"}>
                <div>
                  <b>{item.label}</b>
                  <code>{item.expression}</code>
                </div>
                <div className="row-actions">
                  <button
                    type="button"
                    className={enabled ? "choice-pill active" : "choice-pill"}
                    onClick={() => {
                      if (enabled && activeMetric !== item.id) setSelectedMetrics(selectedMetrics.filter((value) => value !== item.id));
                      if (!enabled) setSelectedMetrics([...selectedMetrics, item.id]);
                    }}
                    disabled={activeMetric === item.id}
                  >
                    {enabled ? "Показан" : "Показать"}
                  </button>
                  <button type="button" className="choice-pill" onClick={() => setActiveMetric(item.id)}>Основной</button>
                  <button type="button" className="choice-pill danger" onClick={() => removeMetric(item.id)}>Удалить</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function validateFormulaExpression(expression: string) {
  if (expression.length > 500) return "Формула слишком длинная. Сократите выражение.";
  if (!/^[0-9A-Za-z_+\-*/%().,\s]+$/.test(expression)) return "Формула содержит неподдерживаемые символы. Используйте поля, числа, скобки и математические операции.";
  const allowedNames = new Set([...FORMULA_VARIABLES.map((item) => item.token), ...FORMULA_FUNCTION_NAMES, "pi", "e"]);
  const identifiers = expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
  const unknown = identifiers.find((item) => !allowedNames.has(item));
  if (unknown) return `Неизвестное поле или функция: ${unknown}. Выберите поле из списка ниже.`;
  let balance = 0;
  for (const char of expression) {
    if (char === "(") balance += 1;
    if (char === ")") balance -= 1;
    if (balance < 0) return "В формуле лишняя закрывающая скобка.";
  }
  if (balance !== 0) return "В формуле не закрыта скобка.";
  const vars = FORMULA_VARIABLES.map((item) => item.token);
  const funcs = [...FORMULA_FUNCTION_NAMES];
  const args = [...vars, ...funcs, "pi", "e"];
  const values = [
    ...vars.map(() => 1),
    ...funcs.map((name) => {
      const map: Record<string, (...args: number[]) => number> = {
        sqrt: Math.sqrt,
        log1p: Math.log1p,
        min: Math.min,
        max: Math.max,
        abs: Math.abs,
        round: Math.round,
        log: Math.log,
        exp: Math.exp,
        pow: Math.pow,
        floor: Math.floor,
        ceil: Math.ceil,
      };
      return map[name];
    }),
    Math.PI,
    Math.E,
  ];
  try {
    const result = Function(...args, `"use strict"; return (${expression});`)(...values);
    if (!Number.isFinite(Number(result))) return "Формула должна возвращать конечное число.";
  } catch {
    return "Формула содержит синтаксическую ошибку. Проверьте операции и скобки.";
  }
  return "";
}

export function FormulaBuilderDialog(props: {
  metrics: CustomMetricDefinition[];
  setMetrics: (value: CustomMetricDefinition[]) => void;
  onSaveMetric: (value: CustomMetricDefinition) => Promise<unknown>;
  onDeleteMetric: (id: string) => Promise<unknown>;
  persistenceReady: boolean;
  selectedMetrics: string[];
  setSelectedMetrics: (value: string[]) => void;
  activeMetric: string;
  setActiveMetric: (value: string) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [props.onClose]);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) props.onClose();
    }}>
      <section className="formula-modal" role="dialog" aria-modal="true" aria-labelledby="formula-builder-title">
        <div className="modal-head">
          <div>
            <span className="step-badge">Рабочее окно</span>
            <h2 id="formula-builder-title">Конструктор собственного показателя</h2>
            <p>Создайте формулу из доступных полей, проверьте пример и включите показатель в рейтинг.</p>
          </div>
          <button type="button" className="icon-button" onClick={props.onClose} aria-label="Закрыть конструктор формул">
            <X size={18} />
          </button>
        </div>
        <CustomMetricBuilder {...props} />
      </section>
    </div>
  );
}

export function safeCustomMetricId(raw: string, fallbackIndex: number) {
  const normalized = raw
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  const value = normalized || `formula_${fallbackIndex}`;
  return (value.startsWith("custom_") ? value : `custom_${value}`).slice(0, 48);
}

export function metricFormulaMarkup(metricName: string) {
  const formulas: Record<string, string> = {
    p: `<math><mrow><mi>P</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mo>|</mo><msub><mi>W</mi><mi>a</mi></msub><mo>|</mo></mrow></math>`,
    c: `<math><mrow><mi>C</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><munderover><mo>∑</mo><mi>i</mi><msub><mi>W</mi><mi>a</mi></msub></munderover><msub><mi>c</mi><mi>i</mi></msub></mrow></math>`,
    c_frac: `<math><mrow><msub><mi>C</mi><mi>д</mi></msub><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><munderover><mo>∑</mo><mi>i</mi><msub><mi>W</mi><mi>a</mi></msub></munderover><mfrac><msub><mi>c</mi><mi>i</mi></msub><msub><mi>n</mi><mi>i</mi></msub></mfrac></mrow></math>`,
    cpp: `<math><mrow><mi>CPP</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mfrac><mrow><mi>C</mi><mo>(</mo><mi>a</mi><mo>)</mo></mrow><mrow><mi>P</mi><mo>(</mo><mi>a</mi><mo>)</mo></mrow></mfrac></mrow></math>`,
    h: `<math><mrow><mi>h</mi><mo>=</mo><mi>max</mi><mo>{</mo><mi>k</mi><mo>:</mo><msub><mi>c</mi><mi>k</mi></msub><mo>≥</mo><mi>k</mi><mo>}</mo></mrow></math>`,
    i10: `<math><mrow><mi>i10</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mo>|</mo><mo>{</mo><mi>i</mi><mo>:</mo><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><mn>10</mn><mo>}</mo><mo>|</mo></mrow></math>`,
    g: `<math><mrow><mi>g</mi><mo>=</mo><mi>max</mi><mo>{</mo><mi>k</mi><mo>:</mo><munderover><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>k</mi></munderover><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><msup><mi>k</mi><mn>2</mn></msup><mo>}</mo></mrow></math>`,
    m_local: `<math><mrow><mi>m</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mfrac><mrow><mi>h</mi><mo>(</mo><mi>a</mi><mo>)</mo></mrow><msub><mi>T</mi><mi>a</mi></msub></mfrac></mrow></math>`,
    f5: `<math><mrow><mi>f5</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mo>|</mo><mo>{</mo><mi>i</mi><mo>:</mo><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><mn>5</mn><mo>}</mo><mo>|</mo></mrow></math>`,
    fm5: `<math><mrow><mi>fm5</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><munderover><mo>∑</mo><mrow><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><mn>5</mn></mrow><msub><mi>W</mi><mi>a</mi></msub></munderover><msub><mi>w</mi><mi>i</mi></msub></mrow></math>`,
    iupv: `<math><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>=</mo><mn>100</mn><mo>·</mo><msup><mrow><mo>(</mo><mi>pr</mi><mo>(</mo><mi>P</mi><mo>)</mo><mo>·</mo><mi>pr</mi><mo>(</mo><mi>h</mi><mo>)</mo><mo>·</mo><mi>pr</mi><mo>(</mo><msub><mi>C</mi><mi>д</mi></msub><mo>)</mo><mo>)</mo></mrow><mfrac><mn>1</mn><mn>3</mn></mfrac></msup></mrow></math>`,
    islv: `<math><mrow><msub><mi>R</mi><mn>2</mn></msub><mo>=</mo><mn>100</mn><mo>·</mo><msub><mi>G</mi><mi>w</mi></msub><mo>(</mo><mi>pr</mi><mo>(</mo><mi>h</mi><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><msub><mi>C</mi><mi>д</mi></msub><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><mi>g</mi><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><mi>i10</mi><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><mi>P</mi><mo>)</mo><mo>)</mo></mrow></math>`,
    lrdi: `<math><mrow><mi>LRDI</mi><mo>=</mo><mi>shrink</mi><mo>(</mo><mi>P</mi><mo>)</mo><mo>·</mo><munderover><mo>∑</mo><mi>i</mi><msub><mi>W</mi><mi>a</mi></msub></munderover><mfrac><mrow><mi>ln</mi><mo>(</mo><mn>1</mn><mo>+</mo><msub><mi>c</mi><mi>i</mi></msub><mo>)</mo></mrow><msub><mi>n</mi><mi>i</mi></msub></mfrac><mo>·</mo><msup><mi>e</mi><mrow><mo>-</mo><mi>λ</mi><mo>·</mo><msub><mi>age</mi><mi>i</mi></msub></mrow></msup></mrow></math>`,
  };
  return (formulas[metricName] ?? "").replace("<math>", '<math xmlns="http://www.w3.org/1998/Math/MathML">');
}
