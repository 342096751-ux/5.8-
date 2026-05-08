<script setup>
const props = defineProps({ modelValue: { type: String, default: "" } });
const emit = defineEmits(["update:modelValue"]);
</script>

<template>
  <textarea
    class="template-textarea"
    :value="modelValue"
    @input="emit('update:modelValue', $event.target.value)"
    placeholder="支持变量：{{input.xxx}} {{self.output.xxx}} {{blackboard.xxx}}"
  />
</template>

<style scoped>
.template-textarea { width:100%; min-height: 120px; resize: vertical; border:1px solid rgba(148,163,184,.35); border-radius:10px; background: rgba(2,6,23,.5); color:#e2e8f0; padding:10px; font-size: 12px; line-height: 1.45; }
</style>
