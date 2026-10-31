package total

import "testing"

func TestSum(t *testing.T) {
	if got := Sum(2, 3, 5); got != 10 {
		t.Fatalf("Sum(2, 3, 5) = %d; want 10", got)
	}
}
