<script setup>
const props = defineProps({ modelValue: { type: String, default: "{}" } });
const emit = defineEmits(["update:modelValue"]);
</script>

<template>
  <textarea
    class="schema-textarea"
    :value="modelValue"
    @input="emit('update:modelValue', $event.target.value)"
    spellcheck="false"
  />
</template>

<style scoped>
.schema-textarea { width:100%; min-height: 150px; resize: vertical; border:1px solid rgba(148,163,184,.35); border-radius:10px; background: rgba(2,6,23,.5); color:#e2e8f0; padding:10px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.45; }
</style>
