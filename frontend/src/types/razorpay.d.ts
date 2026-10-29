export {}

declare global {
  interface RazorpayCheckoutResult {
    razorpay_order_id: string
    razorpay_payment_id: string
    razorpay_signature: string
  }

  interface RazorpayCheckoutOptions {
    key: string
    amount: number
    currency: string
    name: string
    description: string
    order_id: string
    prefill?: { name?: string; email?: string }
    theme?: { color: string }
    handler: (result: RazorpayCheckoutResult) => void | Promise<void>
    modal?: { ondismiss?: () => void }
  }

  interface RazorpayCheckoutInstance {
    open: () => void
    on: (event: string, handler: (response: { error?: { description?: string } }) => void) => void
  }

  interface Window {
    Razorpay?: new (options: RazorpayCheckoutOptions) => RazorpayCheckoutInstance
  }
}
