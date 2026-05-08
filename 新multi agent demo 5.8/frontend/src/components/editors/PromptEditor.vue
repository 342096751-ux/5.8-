<script setup>
const props = defineProps({
  modelValue: { type: String, default: "" },
  placeholder: { type: String, default: "请输入 Prompt" },
});
const emit = defineEmits(["update:modelValue"]);
</script>

<template>
  <div class="editor-wrap">
    <div class="line-gutter" aria-hidden="true">
      <span v-for="n in Math.max(10, String(modelValue || '').split(/\n/).length)" :key="n">{{ n }}</span>
    </div>
    <textarea
      :value="modelValue"
      :placeholder="placeholder"
      @input="emit('update:modelValue', $event.target.value)"
    />
  </div>
</template>

<style scoped>
.editor-wrap { display: grid; grid-template-columns: 34px 1fr; border: 1px solid rgba(148,163,184,.35); border-radius: 10px; overflow: hidden; background: rgba(15,23,42,.35); }
.line-gutter { padding: 8px 4px; font-size: 11px; color: #94a3b8; text-align: right; border-right: 1px solid rgba(148,163,184,.25); line-height: 1.45; }
.line-gutter span { display:block; }
textarea { min-height: 140px; resize: vertical; border: none; outline: none; background: transparent; color: #e2e8f0; font-size: 12px; line-height: 1.45; padding: 8px 10px; }
</style>
