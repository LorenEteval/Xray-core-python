package binding

import "testing"

func TestNewServerFromJSONRejectsInvalidJSON(t *testing.T) {
	t.Parallel()

	if _, err := NewServerFromJSON("{"); err == nil {
		t.Fatal("NewServerFromJSON accepted invalid JSON")
	}
}
