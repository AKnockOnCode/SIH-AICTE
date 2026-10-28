// Minimal React 19 type declarations used ONLY for offline type-checking where the official
// @types/react package is unavailable (see tsconfig.sandbox.json). Normal development uses the
// official types from npm via tsconfig.json. Kept deliberately strict for HTML attributes so that
// misspelled props and wrongly-typed event handlers are still caught.

export type Key = string | number | bigint;
export interface ReactElement<P = any> {
  type: any;
  props: P;
  key: string | null;
}
export type ReactNode = ReactElement | string | number | bigint | boolean | null | undefined | Iterable<ReactNode>;
export type JSXElementConstructor<P> = (props: P) => ReactNode;
export type FC<P = {}> = (props: P) => ReactNode;
export type PropsWithChildren<P = unknown> = P & { children?: ReactNode };

export interface RefObject<T> {
  current: T;
}
export type RefCallback<T> = (instance: T | null) => void | (() => void);
export type Ref<T> = RefCallback<T> | RefObject<T | null> | null;

export type Dispatch<A> = (value: A) => void;
export type SetStateAction<S> = S | ((prevState: S) => S);
export type EffectCallback = () => void | (() => void);
export type DependencyList = readonly unknown[];

export function useState<S>(initialState: S | (() => S)): [S, Dispatch<SetStateAction<S>>];
export function useState<S = undefined>(): [S | undefined, Dispatch<SetStateAction<S | undefined>>];
export function useReducer<S, A>(reducer: (state: S, action: A) => S, initialState: S): [S, Dispatch<A>];
export function useEffect(effect: EffectCallback, deps?: DependencyList): void;
export function useLayoutEffect(effect: EffectCallback, deps?: DependencyList): void;
export function useMemo<T>(factory: () => T, deps: DependencyList): T;
export function useCallback<T extends Function>(callback: T, deps: DependencyList): T;
export function useRef<T>(initialValue: T): RefObject<T>;
export function useRef<T>(initialValue: T | null): RefObject<T | null>;
export function useRef<T>(initialValue: T | undefined): RefObject<T | undefined>;
export function useId(): string;
export function useSyncExternalStore<T>(subscribe: (onChange: () => void) => () => void, getSnapshot: () => T,
  getServerSnapshot?: () => T): T;
export function useDeferredValue<T>(value: T): T;
export function useTransition(): [boolean, (callback: () => void) => void];

export interface ProviderProps<T> {
  value: T;
  children?: ReactNode;
}
export interface Context<T> {
  Provider: (props: ProviderProps<T>) => ReactNode;
  displayName?: string;
}
export function createContext<T>(defaultValue: T): Context<T>;
export function useContext<T>(context: Context<T>): T;
export function memo<P>(component: (props: P) => ReactNode): (props: P) => ReactNode;
export const Fragment: (props: { children?: ReactNode }) => ReactNode;
export const StrictMode: (props: { children?: ReactNode }) => ReactNode;

// ---------------------------------------------------------------------------- events
export interface BaseSyntheticEvent<E = object, C = any, T = any> {
  nativeEvent: E;
  currentTarget: C;
  target: T;
  bubbles: boolean;
  defaultPrevented: boolean;
  type: string;
  timeStamp: number;
  preventDefault(): void;
  stopPropagation(): void;
  isDefaultPrevented(): boolean;
  isPropagationStopped(): boolean;
}
export interface SyntheticEvent<T = Element, E = Event> extends BaseSyntheticEvent<E, EventTarget & T, EventTarget> {}
export interface UIEvent<T = Element, E = globalThis.UIEvent> extends SyntheticEvent<T, E> {
  detail: number;
}
export interface MouseEvent<T = Element, E = globalThis.MouseEvent> extends UIEvent<T, E> {
  altKey: boolean;
  button: number;
  buttons: number;
  clientX: number;
  clientY: number;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  pageX: number;
  pageY: number;
}
export interface PointerEvent<T = Element> extends MouseEvent<T, globalThis.PointerEvent> {
  pointerId: number;
  pointerType: string;
}
export interface DragEvent<T = Element> extends MouseEvent<T, globalThis.DragEvent> {
  dataTransfer: DataTransfer;
}
export interface FocusEvent<Target = Element, RelatedTarget = Element> extends SyntheticEvent<Target, globalThis.FocusEvent> {
  relatedTarget: (EventTarget & RelatedTarget) | null;
  target: EventTarget & Target;
}
export interface KeyboardEvent<T = Element> extends UIEvent<T, globalThis.KeyboardEvent> {
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  key: string;
  code: string;
  repeat: boolean;
}
export interface FormEvent<T = Element> extends SyntheticEvent<T> {}
export interface ChangeEvent<T = Element> extends SyntheticEvent<T> {
  target: EventTarget & T;
}
export interface WheelEvent<T = Element> extends MouseEvent<T, globalThis.WheelEvent> {
  deltaX: number;
  deltaY: number;
}

type EventHandler<E> = (event: E) => void;
export type MouseEventHandler<T = Element> = EventHandler<MouseEvent<T>>;
export type ChangeEventHandler<T = Element> = EventHandler<ChangeEvent<T>>;
export type KeyboardEventHandler<T = Element> = EventHandler<KeyboardEvent<T>>;
export type FormEventHandler<T = Element> = EventHandler<FormEvent<T>>;

export interface CSSProperties {
  [property: string]: string | number | undefined;
}

// ---------------------------------------------------------------------------- attributes
export interface DOMAttributes<T> {
  children?: ReactNode;
  dangerouslySetInnerHTML?: { __html: string };
  onClick?: MouseEventHandler<T>;
  onDoubleClick?: MouseEventHandler<T>;
  onMouseDown?: MouseEventHandler<T>;
  onMouseUp?: MouseEventHandler<T>;
  onMouseEnter?: MouseEventHandler<T>;
  onMouseLeave?: MouseEventHandler<T>;
  onMouseMove?: MouseEventHandler<T>;
  onMouseOver?: MouseEventHandler<T>;
  onContextMenu?: MouseEventHandler<T>;
  onPointerDown?: EventHandler<PointerEvent<T>>;
  onPointerUp?: EventHandler<PointerEvent<T>>;
  onPointerMove?: EventHandler<PointerEvent<T>>;
  onKeyDown?: KeyboardEventHandler<T>;
  onKeyUp?: KeyboardEventHandler<T>;
  onChange?: ChangeEventHandler<T>;
  onInput?: FormEventHandler<T>;
  onSubmit?: FormEventHandler<T>;
  onReset?: FormEventHandler<T>;
  onInvalid?: FormEventHandler<T>;
  onFocus?: EventHandler<FocusEvent<T>>;
  onBlur?: EventHandler<FocusEvent<T>>;
  onDragEnter?: EventHandler<DragEvent<T>>;
  onDragOver?: EventHandler<DragEvent<T>>;
  onDragLeave?: EventHandler<DragEvent<T>>;
  onDrop?: EventHandler<DragEvent<T>>;
  onScroll?: EventHandler<UIEvent<T>>;
  onWheel?: EventHandler<WheelEvent<T>>;
  onToggle?: EventHandler<SyntheticEvent<T>>;
  onLoad?: EventHandler<SyntheticEvent<T>>;
  onError?: EventHandler<SyntheticEvent<T>>;
}

type Booleanish = boolean | "true" | "false";

export interface HTMLAttributes<T> extends DOMAttributes<T> {
  ref?: Ref<T>;
  key?: Key | null;
  accessKey?: string;
  autoFocus?: boolean;
  className?: string;
  contentEditable?: Booleanish | "inherit";
  dir?: string;
  draggable?: Booleanish;
  hidden?: boolean;
  id?: string;
  lang?: string;
  role?: string;
  slot?: string;
  spellCheck?: Booleanish;
  style?: CSSProperties;
  tabIndex?: number;
  title?: string;
  translate?: "yes" | "no";
  inert?: boolean;
  inputMode?: "none" | "text" | "tel" | "url" | "email" | "numeric" | "decimal" | "search";
  [aria: `aria-${string}`]: string | number | boolean | undefined;
  [data: `data-${string}`]: string | number | boolean | undefined;
}

export interface AllHTMLAttributes<T> extends HTMLAttributes<T> {
  accept?: string;
  action?: string;
  allowFullScreen?: boolean;
  alt?: string;
  autoComplete?: string;
  checked?: boolean;
  cite?: string;
  colSpan?: number;
  cols?: number;
  dateTime?: string;
  defaultChecked?: boolean;
  defaultValue?: string | number | readonly string[];
  disabled?: boolean;
  download?: any;
  encType?: string;
  form?: string;
  height?: number | string;
  high?: number;
  href?: string;
  hrefLang?: string;
  htmlFor?: string;
  label?: string;
  list?: string;
  loading?: "eager" | "lazy";
  low?: number;
  max?: number | string;
  maxLength?: number;
  method?: string;
  min?: number | string;
  minLength?: number;
  multiple?: boolean;
  name?: string;
  noValidate?: boolean;
  open?: boolean;
  optimum?: number;
  pattern?: string;
  placeholder?: string;
  readOnly?: boolean;
  rel?: string;
  required?: boolean;
  reversed?: boolean;
  rowSpan?: number;
  rows?: number;
  scope?: string;
  selected?: boolean;
  size?: number;
  span?: number;
  src?: string;
  start?: number;
  step?: number | string;
  target?: string;
  type?: string;
  value?: string | readonly string[] | number;
  width?: number | string;
  wrap?: string;
}

export interface SVGAttributes<T> extends DOMAttributes<T> {
  ref?: Ref<T>;
  key?: Key | null;
  className?: string;
  style?: CSSProperties;
  role?: string;
  tabIndex?: number;
  id?: string;
  [attribute: string]: any;
}

type H<T> = AllHTMLAttributes<T>;
type S<T> = SVGAttributes<T>;

export namespace JSX {
  type ElementType = string | JSXElementConstructor<any>;
  interface Element extends ReactElement<any> {}
  interface ElementClass {}
  interface ElementAttributesProperty {
    props: {};
  }
  interface ElementChildrenAttribute {
    children: {};
  }
  interface IntrinsicAttributes {
    key?: Key | null;
  }
  interface IntrinsicClassAttributes<T> {
    ref?: Ref<T>;
  }
  interface IntrinsicElements {
    a: H<HTMLAnchorElement>;
    abbr: H<HTMLElement>;
    article: H<HTMLElement>;
    aside: H<HTMLElement>;
    b: H<HTMLElement>;
    blockquote: H<HTMLQuoteElement>;
    br: H<HTMLBRElement>;
    button: H<HTMLButtonElement>;
    caption: H<HTMLElement>;
    code: H<HTMLElement>;
    col: H<HTMLTableColElement>;
    colgroup: H<HTMLTableColElement>;
    dd: H<HTMLElement>;
    del: H<HTMLModElement>;
    details: H<HTMLDetailsElement>;
    dfn: H<HTMLElement>;
    dialog: H<HTMLDialogElement>;
    div: H<HTMLDivElement>;
    dl: H<HTMLDListElement>;
    dt: H<HTMLElement>;
    em: H<HTMLElement>;
    fieldset: H<HTMLFieldSetElement>;
    figcaption: H<HTMLElement>;
    figure: H<HTMLElement>;
    footer: H<HTMLElement>;
    form: H<HTMLFormElement>;
    h1: H<HTMLHeadingElement>;
    h2: H<HTMLHeadingElement>;
    h3: H<HTMLHeadingElement>;
    h4: H<HTMLHeadingElement>;
    h5: H<HTMLHeadingElement>;
    h6: H<HTMLHeadingElement>;
    header: H<HTMLElement>;
    hr: H<HTMLHRElement>;
    i: H<HTMLElement>;
    img: H<HTMLImageElement>;
    input: H<HTMLInputElement>;
    ins: H<HTMLModElement>;
    kbd: H<HTMLElement>;
    label: H<HTMLLabelElement>;
    legend: H<HTMLLegendElement>;
    li: H<HTMLLIElement>;
    main: H<HTMLElement>;
    mark: H<HTMLElement>;
    menu: H<HTMLElement>;
    meter: H<HTMLMeterElement>;
    nav: H<HTMLElement>;
    ol: H<HTMLOListElement>;
    optgroup: H<HTMLOptGroupElement>;
    option: H<HTMLOptionElement>;
    output: H<HTMLOutputElement>;
    p: H<HTMLParagraphElement>;
    pre: H<HTMLPreElement>;
    progress: H<HTMLProgressElement>;
    q: H<HTMLQuoteElement>;
    s: H<HTMLElement>;
    section: H<HTMLElement>;
    select: H<HTMLSelectElement>;
    small: H<HTMLElement>;
    span: H<HTMLSpanElement>;
    strong: H<HTMLElement>;
    sub: H<HTMLElement>;
    summary: H<HTMLElement>;
    sup: H<HTMLElement>;
    table: H<HTMLTableElement>;
    tbody: H<HTMLTableSectionElement>;
    td: H<HTMLTableCellElement>;
    textarea: H<HTMLTextAreaElement>;
    tfoot: H<HTMLTableSectionElement>;
    th: H<HTMLTableCellElement>;
    thead: H<HTMLTableSectionElement>;
    time: H<HTMLTimeElement>;
    tr: H<HTMLTableRowElement>;
    u: H<HTMLElement>;
    ul: H<HTMLUListElement>;
    var: H<HTMLElement>;
    svg: S<SVGSVGElement>;
    circle: S<SVGCircleElement>;
    clipPath: S<SVGClipPathElement>;
    defs: S<SVGDefsElement>;
    ellipse: S<SVGEllipseElement>;
    foreignObject: S<SVGForeignObjectElement>;
    g: S<SVGGElement>;
    line: S<SVGLineElement>;
    linearGradient: S<SVGLinearGradientElement>;
    marker: S<SVGMarkerElement>;
    path: S<SVGPathElement>;
    pattern: S<SVGPatternElement>;
    polygon: S<SVGPolygonElement>;
    polyline: S<SVGPolylineElement>;
    rect: S<SVGRectElement>;
    stop: S<SVGStopElement>;
    text: S<SVGTextElement>;
    title: S<SVGTitleElement>;
    tspan: S<SVGTSpanElement>;
  }
}
