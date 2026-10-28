export type Product = {
  id: number;
  name: string;
  source: string;
  source_published_at?: string | null;
  source_new_badge?: boolean;
  brand: string | null;
  category: string | null;
  imported_category?: string | null;
  price: string | null;
  old_price: string | null;
  currency: string | null;
  image_url: string | null;
  image_urls?: string[];
  thumbnail_url?: string | null;
  photo_urls?: string[];
  photo_thumbnails?: string[];
  image_count?: number;
  product_url: string | null;
  description: string | null;
  sizes: string[] | null;
  heights: string[] | null;
  difficulty: string | null;
  audience: string | null;
  is_sale: boolean;
  is_new: boolean;
  is_free: boolean;
  is_beginner: boolean;
  is_knit: boolean;
  is_available: boolean;
  hidden?: boolean;
  source_enabled?: boolean;
};
export type UIItem = { key: string; enabled: boolean };
export type UISettings = { filters: UIItem[]; menu: UIItem[] };
export type Meta = {
  coverage: {counts: Record<string,number>; unknown_audience:number; total:number; publication_dates?:number; new_window_days?:number};
  ui: UISettings;
  categories: { name: string; count: number }[];
  brands: { source: string; name: string; count: number }[];
  category_options: string[];
  local_login: boolean;
};
export type Page = { items: Product[]; total: number };
export type Source = {
  name: string;
  display_name: string;
  base_url: string;
  enabled: boolean;
  products: number;
  parser_status: string;
};
type Telegram = {
  initData: string;
  colorScheme: string;
  ready: () => void;
  expand: () => void;
  onEvent: (event: string, fn: () => void) => void;
  offEvent: (event: string, fn: () => void) => void;
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (fn: () => void) => void;
    offClick: (fn: () => void) => void;
  };
};
export const tg = (window as Window & { Telegram?: { WebApp: Telegram } })
  .Telegram?.WebApp;
let devKey = "";
export function setDevKey(value: string) {
  devKey = value;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (tg?.initData) headers["X-Telegram-Init-Data"] = tg.initData;
  if (devKey) headers["X-Dev-Key"] = devKey;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!response.ok)
    throw new Error(
      response.status === 401
        ? "Сессия истекла. Переоткройте каталог из Telegram."
        : response.status === 403 ? "Для этого действия нужны права администратора."
        : `Не удалось выполнить запрос (${response.status}). Попробуйте ещё раз.`,
    );
  return response.json();
}
export function money(p: Product) {
  return p.is_free
    ? "Бесплатно"
    : p.price === null
      ? "Цена в магазине"
      : `${Number(p.price).toLocaleString("ru-RU")} ${p.currency === "RUB" ? "₽" : p.currency || ""}`;
}
export const labels: Record<string, string> = {
  search: "Поиск",
  category: "Категория",
  source: "Бренд",
  audience: "Для кого",
  is_new: "Новинки",
  is_sale: "Скидки",
  is_free: "Бесплатные и за 1 ₽",
  is_beginner: "Для начинающих",
  is_knit: "Трикотаж",
  sort: "Сортировка",
  women: "Женские",
  men: "Мужские",
  kids: "Детские",
  unisex: "Унисекс",
};
