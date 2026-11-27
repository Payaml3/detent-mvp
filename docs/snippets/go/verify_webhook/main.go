// Run the signature vectors: go run ./verify_webhook ../webhook-vectors.txt
package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

func main() {
	file, err := os.Open(os.Args[1])
	if err != nil {
		panic(err)
	}
	defer file.Close()
	failures := 0
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.SplitN(line, "|", 6)
		now, _ := strconv.ParseInt(f[3], 10, 64)
		if VerifyWebhook(f[2], f[4], []byte(f[5]), now, 300) != (f[1] == "ok") {
			fmt.Printf("FAIL %s: expected %s\n", f[0], f[1])
			failures++
		}
	}
	if failures > 0 {
		fmt.Printf("go: %d vector(s) failed\n", failures)
		os.Exit(1)
	}
	fmt.Println("go: all vectors pass")
}
