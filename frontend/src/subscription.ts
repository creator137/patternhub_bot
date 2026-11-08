import {ref} from 'vue';
import {api, tg} from './api';
export type Plan = {enabled:boolean;price_kopecks:number;terms_url:string;support_url:string;payments_ready:boolean;test:boolean};
export type Access = {trial_available:boolean;trial_end:number|null;access_until:number|null;has_access:boolean;state:string};
export const plan = ref<Plan|null>(null);
export const access = ref<Access|null>(null);
export async function refreshSubscription() {
  plan.value = await api<Plan>('/subscription/plan');
  if (tg?.initData) access.value = await api<Access>('/subscription');
}
export function rub(kopecks:number) {return (kopecks/100).toLocaleString('ru-RU',{style:'currency',currency:'RUB'});}
export function until(seconds:number|null) {return seconds ? new Date(seconds*1000).toLocaleString('ru-RU') : '—';}
