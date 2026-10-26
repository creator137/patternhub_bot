import { createApp } from "vue";
import PrimeVue from "primevue/config";
import Aura from "@primeuix/themes/aura";
import { definePreset } from "@primeuix/themes";
import App from "./App.vue";
import "primeicons/primeicons.css";
import "@fontsource-variable/manrope";
import "@fontsource/prata";
import "./style.css";
import "./controls.css";
const PatternHub = definePreset(Aura, {
  semantic: {
    primary: {
      50: "#f1f5ee",
      100: "#e4ebdd",
      200: "#cad8bd",
      300: "#abc096",
      400: "#8aa472",
      500: "#698653",
      600: "#526d40",
      700: "#3e5432",
      800: "#34452c",
      900: "#2c3b26",
      950: "#172113",
    },
    colorScheme: {
      light: {
        primary: {
          color: "#364e3c",
          contrastColor: "#ffffff",
          hoverColor: "#283d2d",
          activeColor: "#1d3021",
        },
        highlight: {
          background: "#edf2e8",
          focusBackground: "#dfe9d7",
          color: "#344e2c",
          focusColor: "#263d20",
        },
        formField: {
          background: "#ffffff",
          borderColor: "#dedfd7",
          hoverBorderColor: "#a0ad96",
          focusBorderColor: "#526d40",
          color: "#252923",
          placeholderColor: "#777a72",
          shadow: "none",
        },
      },
      dark: {
        primary: {
          color: "#b3cc9e",
          contrastColor: "#182315",
          hoverColor: "#c8ddb7",
          activeColor: "#dbe9cf",
        },
        highlight: {
          background: "#36482e",
          focusBackground: "#435838",
          color: "#d9ebcc",
          focusColor: "#edf5e6",
        },
        formField: {
          background: "#262e25",
          borderColor: "#485142",
          hoverBorderColor: "#7d9070",
          focusBorderColor: "#b3cc9e",
          color: "#eff0e9",
          placeholderColor: "#a8b1a3",
          shadow: "none",
        },
      },
    },
  },
  components: {
    select: {
      root: { borderRadius: "12px", paddingX: "14px", paddingY: "13px" },
      dropdown: { width: "44px" },
      overlay: { borderRadius: "14px" },
      list: { padding: "6px", gap: "3px" },
      option: { padding: "12px", borderRadius: "8px" },
    },
    inputtext: {
      root: { borderRadius: "12px", paddingX: "14px", paddingY: "13px" },
    },
    button: {
      root: { borderRadius: "12px", paddingX: "18px", paddingY: "12px" },
    },
    toggleswitch: {
      root: { width: "42px", height: "24px" },
      handle: { size: "18px" },
    },
  },
});
createApp(App)
  .use(PrimeVue, {
    theme: { preset: PatternHub, options: { darkModeSelector: ".dark" } },
    locale: {
      emptyMessage: "Ничего не найдено",
      emptyFilterMessage: "Нет подходящих вариантов",
      searchMessage: "Найдено вариантов: {0}",
      selectionMessage: "Выбрано: {0}",
      emptySelectionMessage: "Ничего не выбрано",
      aria: { close: "Закрыть", clear: "Очистить" },
    },
  })
  .mount("#app");
