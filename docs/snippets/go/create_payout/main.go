// Create the quickstart payout. Run from a folder that holds payout.json: go run ./create_payout
package main

// docs:start
import (
	"bytes"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
)

func main() {
	body, err := os.ReadFile("payout.json")
	if err != nil {
		panic(err)
	}
	key := make([]byte, 16)
	rand.Read(key)
	req, _ := http.NewRequest("POST", os.Getenv("DEKERNAI_BASE_URL")+"/v1/payment_intents", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+os.Getenv("DEKERNAI_API_KEY"))
	req.Header.Set("Idempotency-Key", fmt.Sprintf("%x", key))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()
	var payment map[string]any
	json.NewDecoder(resp.Body).Decode(&payment)
	if resp.StatusCode >= 300 {
		panic(fmt.Sprint(resp.StatusCode, payment))
	}
	fmt.Println(payment["id"], payment["status"])
}

// docs:end
