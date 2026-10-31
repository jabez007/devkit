package total

func Sum(values ...int) int {
	result := 0
	for _, value := range values {
		result += value
	}
	return result
}
