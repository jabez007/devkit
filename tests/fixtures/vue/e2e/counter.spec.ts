import { expect, test } from '@playwright/test'

test('a keyboard user advances the counter once', async ({ page }) => {
  await page.goto('/')
  const button = page.getByRole('button', { name: 'Count: 0', exact: true })
  await button.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Count: 1', exact: true })).toBeVisible()
})
