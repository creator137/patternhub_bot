<script setup lang="ts">
import { useAttrs } from "vue";
import PrimeSelect from "primevue/select";
defineOptions({ inheritAttrs: false });
const attrs = useAttrs();
</script>
<template>
  <PrimeSelect
    v-bind="attrs"
    :filter="Array.isArray(attrs.options) && attrs.options.length > 8"
    filterPlaceholder="Найти вариант"
    checkmark
    scrollHeight="260px"
    :aria-label="
      String(attrs['aria-label'] || attrs.placeholder || 'Выберите вариант')
    "
    class="catalog-select"
  >
    <template #dropdownicon
      ><i class="pi pi-chevron-down select-chevron" aria-hidden="true"></i
    ></template>
  </PrimeSelect>
</template>
