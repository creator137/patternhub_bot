import {tg} from './api';

// Best effort: opening a shop must never wait for the analytics endpoint.
export function trackEvent(kind: 'open' | 'outbound', destination: {source?: string; product_id?: number} = {}) {
  if (!tg?.initData) return; // Only verified Telegram visitors enter the counters.
  const event = {event_id: crypto.randomUUID(), kind, ...destination};
  const headers = {'Content-Type':'application/json','X-Telegram-Init-Data':tg.initData};
  async function send() {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await fetch('/api/events', {method:'POST', headers,
          body:JSON.stringify(event), keepalive:true, signal:AbortSignal.timeout(4000)});
        if (response.ok || response.status < 500) return;
      } catch { /* Retry once with the same ID, without blocking navigation. */ }
      if (!attempt) await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
  void send();
}

export type AnalyticsSummary = {
  days:number; since:string|null; timezone:string;
  users:number; opens:number; clicks:number; outbound_users:number;
  sources:{source:string;name:string;clicks:number;users:number}[];
  daily:{day:string;users:number;opens:number;clicks:number}[];
};
