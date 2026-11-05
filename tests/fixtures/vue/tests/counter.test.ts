import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import CounterButton from '../src/CounterButton.vue'

test('one click advances the counter by one', async () => {
  const wrapper = mount(CounterButton)
  expect(wrapper.get('button').text()).toBe('Count: 0')
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('button').text()).toBe('Count: 1')
})
