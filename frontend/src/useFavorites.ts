import { ref } from 'vue';
import { api, tg } from './api';

export function useFavorites() {
  const ids = ref<number[]>([]), pending = ref(new Set<number>()), notice = ref('');
  const server = !!tg?.initData;
  function localRead() {
    try {
      const stored = JSON.parse(localStorage.getItem('allsewpattern.favorites') || '[]');
      return Array.isArray(stored) ? [...new Set(stored.filter(v => Number.isInteger(v) && v > 0))].slice(0, 500) as number[] : [];
    } catch { return []; }
  }
  if (!server) ids.value = localRead();
  async function initialize() {
    if (!server) return;
    try { ids.value = (await api<{ ids: number[] }>('/favorites')).ids; }
    catch { notice.value = 'Не удалось загрузить избранное. Переоткройте каталог из Telegram.'; }
  }
  async function toggle(id: number) {
    if (pending.value.has(id)) return;
    const saved = !ids.value.includes(id);
    if (saved && ids.value.length >= 500) { notice.value = 'В избранном уже 500 выкроек.'; return; }
    pending.value.add(id);
    ids.value = saved ? [...ids.value, id] : ids.value.filter(value => value !== id);
    try {
      if (server) await api('/favorites/' + id, 'PUT', { saved });
      else {
        try { localStorage.setItem('allsewpattern.favorites', JSON.stringify(ids.value)); }
        catch { notice.value = 'Браузер не разрешил сохранить избранное на устройстве.'; }
      }
    } catch (error) {
      ids.value = saved ? ids.value.filter(value => value !== id) : [...ids.value, id];
      notice.value = (error as Error).message;
    } finally { pending.value.delete(id); }
  }
  return { ids, pending, notice, initialize, toggle };
}
